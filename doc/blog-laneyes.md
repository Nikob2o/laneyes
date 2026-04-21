---
title: "LanEyes — un scanner réseau maison, déployé en GitOps sur K3s"
date: 2026-04-19
tags: [homelab, kubernetes, gitops, argocd, flask, network]
---

## Le point de départ

Je voulais savoir **qui vit sur mon LAN**. Pas juste la box qui affiche « 12 appareils connectés » sans plus de détail, mais un vrai inventaire : IP, MAC, vendor, OS, hostname, premier/dernier vu, avec un historique et la possibilité de nommer chaque device moi-même.

Rien de révolutionnaire — mais rien sur étagère ne collait exactement à ce que je voulais. Alors j'ai codé **LanEyes**.

## Ce que ça fait

- **Quick scan** : ARP + ping multi-méthode (ICMP, TCP ACK sur 80/443, table ARP système) pour ratisser un `/24` en quelques secondes.
- **Deep scan** : nmap OS/service detection sur les hôtes vivants.
- **Historique** : chaque passage d'un device est loggé, on garde la trace même quand il disparaît du réseau.
- **Dashboard** : compteurs (total, online, nouveaux de la semaine, ghost devices), timeline des scans, top vendors, répartition OS.
- **Logs** : chaque scan produit un `ScanEvent` (success / partial / failed) avec message et durée — utile quand un deep scan foire silencieusement.

Stack : Flask + SQLAlchemy + SQLite, `python-nmap`, `mac-vendor-lookup`, Chart.js côté front.

## Le vrai sujet : le déploiement

La partie intéressante à raconter n'est pas le code Flask, c'est **comment ça arrive sur mon cluster**.

### Le cluster

Un K3s qui tourne sur 3 Raspberry Pi (1 master, 2 workers), monté à l'Ansible. ArgoCD gère le GitOps, cert-manager produit les certificats Let's Encrypt via DNS-01, et Pi-hole fait office de DNS local pour que `laneyes.home-fonta.fr` résolve vers l'IP d'un node sur le LAN — pas d'exposition publique, tout reste chez moi.

### La contrainte particulière

Scanner un LAN depuis un pod, ça demande deux choses que Kubernetes n'aime pas donner à la légère :

- **`hostNetwork: true`** — sinon le pod voit le réseau du cluster (CNI), pas le vrai LAN.
- **capabilities `NET_RAW` + `NET_ADMIN`** — pour qu'nmap puisse envoyer des paquets ARP et des probes bruts.

Dans le chart Helm :

```yaml
hostNetwork: true
securityContext:
  capabilities:
    add:
      - NET_RAW
      - NET_ADMIN
```

### Le piège ArgoCD `:latest`

Au début, j'ai bêtement tagué mon image `:latest`. La CI build, push sur Docker Hub, et… rien ne bouge. Je force un sync ArgoCD, il me dit « in sync ». Logique : **ArgoCD synchronise des manifestes Kubernetes, pas des images Docker**. Le tag dans `values.yaml` n'a pas changé, donc le Deployment n'a pas changé, donc ArgoCD n'a rien à faire. Et Kubernetes de son côté ne re-pull pas tant que le tag ne bouge pas.

La solution propre, celle que j'utilise déjà pour mon site `home-fonta` : **faire de la CI le bras armé de GitOps**. Le build pousse l'image taguée par SHA court, et un deuxième workflow patch `values.yaml` dans le repo `ansible-k3s` avec ce nouveau tag. Commit, push, ArgoCD voit un diff, déploie.

### Le workflow

```yaml
name: Update Helm Chart
on:
  workflow_run:
    workflows: ["CI - Build & Push"]
    types: [completed]
    branches: [main]

jobs:
  update-helm:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    steps:
      - name: Checkout ansible-k3s
        uses: actions/checkout@v4
        with:
          repository: Nikob2o/ansible-k3s
          token: ${{ secrets.PAT_TOKEN }}
          path: ansible-k3s

      - name: Bump tag
        run: |
          SHORT_SHA=$(echo ${{ github.event.workflow_run.head_sha }} | cut -c1-7)
          cd ansible-k3s
          sed -i "s|tag: .*|tag: sha-${SHORT_SHA}|" helm-charts/laneyes/values.yaml

      - name: Commit & push
        run: |
          cd ansible-k3s
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add helm-charts/laneyes/values.yaml
          git diff --staged --quiet || git commit -m "Bump laneyes image"
          git push
```

Il faut un PAT (fine-grained, scope `Contents: read/write` sur le repo `ansible-k3s` uniquement) stocké en secret `PAT_TOKEN` dans le repo de l'app.

### Le flow complet

```
push sur laneyes/main
        ↓
CI build multi-arch (amd64 + arm64) → push nocoblas/laneyes:sha-abc1234
        ↓
workflow update-helm → sed dans ansible-k3s/helm-charts/laneyes/values.yaml → commit
        ↓
ArgoCD détecte le diff (polling 3 min, ou webhook)
        ↓
helm upgrade → rolling update → nouveau pod qui pull l'image
        ↓
laneyes.home-fonta.fr sert la nouvelle version
```

Tout est traçable dans Git. Rollback = `git revert` sur le commit du bot. Pas de `kubectl apply` manuel, pas de `rollout restart` à lancer à la main.

## Ce que j'en retiens

- **Pour le GitOps "vrai", le tag `:latest` est un faux ami**. C'est pratique en dev, mais ArgoCD ne peut littéralement pas savoir qu'il y a une nouvelle version.
- **Le pattern "deux workflows" (build + update-helm)** est simple, lisible, et découpe proprement les responsabilités : un repo possède le code, l'autre possède l'état désiré du cluster.
- **`hostNetwork` + capabilities** suffisent pour faire passer un scanner réseau dans K8s, pas besoin d'aller sur du `privileged`.
- **Scanner un LAN depuis un conteneur sur un Pi qui tourne sur le même réseau**, c'est un peu méta et très satisfaisant.

## Code

- App : [github.com/Nikob2o/laneyes](https://github.com/Nikob2o/laneyes)
- Chart + ArgoCD app : [github.com/Nikob2o/ansible-k3s](https://github.com/Nikob2o/ansible-k3s)
