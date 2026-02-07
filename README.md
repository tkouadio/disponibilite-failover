# MGL7361 : Principes et applications de la conception de logiciels
# Projet 1 : Tactiques de disponibilité (Détection + Redondance)
**Preuve de concept - FastAPI + Docker Compose**

## 🎯 Objectif
Cette application web simple démontre deux tactiques de disponibilité telles que définies par **Bass et al.** :

1. **Détection de défaillance**  
   (sondage périodique de l’état des services via des health checks)
2. **Récupération après panne par redondance**  
   (basculement automatique vers un nœud de secours)

Un **stimulus manuel** permet de provoquer une défaillance simulée afin d’observer la réaction du système, le basculement vers le nœud de secours et de mesurer objectivement la **résilience** du système.

Ce stimulus correspond explicitement à un *stimulus de défaillance* au sens de Bass et al., permettant d’analyser la réponse architecturale du système.

---

## 🏗️ Architecture (résumé)

```

Client
|
v

| Supervisor / Router (Failover + métriques)        |
| ------------------------------------------------- |
| v                              v                  |
| Service A (primaire)          Service B (secours) |
| API Orders + stimulus         API Orders          |

```

### Rôles des composants
- **Service A (primaire)**  
  Service principal ciblé en priorité. Il intègre un mécanisme de **panne simulée** déclenchée manuellement.
- **Service B (secondaire / spare)**  
  Service redondant, prêt à prendre le relais en cas de défaillance du primaire.
- **Supervisor / Router**  
  Point d’entrée unique de l’application. Il assure :
  - la **détection de défaillance** via des appels périodiques à `/health`,
  - le **basculement automatique (failover)** vers le service sain,
  - la **collecte horodatée des requêtes et statuts HTTP** afin de calculer les métriques de résilience.

---

## 📦 Structure du dépôt

```

disponibilite-failover/
├─ docker-compose.yml
├─ README.md
├─ service/
│  ├─ Dockerfile
│  ├─ requirements.txt
│  └─ app.py
└─ superviseur/
├─ Dockerfile
├─ requirements.txt
└─ app.py

````

---

# ✅ Exécution (Docker - recommandée)

## Prérequis
- Docker Desktop

## Lancer l’application
```bash
docker compose up --build
````

## Accès aux endpoints

* Swagger (Supervisor) : [http://localhost:8000/docs](http://localhost:8000/docs)
* État logique : [http://localhost:8000/status](http://localhost:8000/status)
* Santé du système : [http://localhost:8000/health](http://localhost:8000/health)
* Décision de routage : [http://localhost:8000/route](http://localhost:8000/route)
* Appel métier (exemple) : [http://localhost:8000/orders/1003](http://localhost:8000/orders/1003)

---

# 💥 Stimulus manuel - Simulation de panne

## 0) Réinitialisation (optionnelle, avant une démonstration)

Via Swagger :

```
POST /stimulus/reset-metrics
```

---

## 1) Génération de trafic (pour la mesure)

### Option A - PowerShell (Windows)

Envoie environ 5 requêtes par seconde pendant ~15 secondes :

```powershell
for ($i=0; $i -lt 75; $i++) { 
  try { Invoke-RestMethod http://localhost:8000/orders/1003 | Out-Null } catch {}
  Start-Sleep -Milliseconds 200
}
```

### Option B - Bash (Linux/macOS/WSL/Git Bash)

> Prérequis : `curl` (généralement déjà disponible)

```bash
for i in $(seq 1 75); do
  curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/orders/1003 || true
  sleep 0.2
done
```

---

## 2) Déclenchement manuel de la panne (stimulus)

Via Swagger :

```
POST /stimulus/fail-primary
```

Paramètre :

* `reason` (ex. : `demo`)

À partir de ce moment :

* **Service A** renvoie volontairement des erreurs (500),
* Le **Supervisor** détecte la défaillance,
* Le **failover** vers **Service B** est déclenché.

---

## 3) Observation du basculement

Pendant la génération de trafic, les réponses continuent à être servies grâce au **Service B (secours)**, démontrant la récupération après panne par redondance.

---

# 📊 Métriques de résilience

## Endpoint

```
GET /metrics
```

### Paramètres (optionnels)

* `pre_window_s` : secondes **avant** la panne (défaut : 2)
* `post_window_s` : secondes **après** la panne (défaut : 10)

---

## (1) Temps de bascule — `T_bascule`

Deux définitions acceptables sont fournies, conformément à l’énoncé :

* `tbascule_200_spare_s`
  Temps entre l’injection de la panne et la première réponse `200` provenant du nœud de secours.
* `tbascule_from_first_error_s`
  Temps entre la première erreur observée et la première réponse `200` du nœud de secours.

---

## (2) Taux d’erreurs pendant la bascule — `E_bascule`

* `error_rate_percent` : pourcentage de requêtes échouées (`status != 200`)
  dans la fenêtre temporelle :

  ```
  [t_panne - pre_window_s ; t_panne + post_window_s]
  ```

---

# ✅ Exécution sans Docker (fallback)

Cette option est fournie afin de faciliter la correction si Docker n’est pas utilisé.
Elle fonctionne autant avec **PowerShell (Windows)** qu’avec **Bash (Linux/macOS/WSL/Git Bash)**.

## Prérequis

* Python 3.10+

## Installation

Dans les dossiers `service` et `superviseur` :

```bash
pip install -r requirements.txt
```

---

## Lancer l’application — Option A (PowerShell / Windows)

### Terminal 1 — Service A

```powershell
cd service
$env:SERVICE_NAME="Service A"
uvicorn app:app --port 8001
```

### Terminal 2 — Service B

```powershell
cd service
$env:SERVICE_NAME="Service B"
uvicorn app:app --port 8002
```

### Terminal 3 — Supervisor / Router

```powershell
cd superviseur
$env:PRIMARY_URL="http://localhost:8001"
$env:SECONDARY_URL="http://localhost:8002"
$env:HEALTH_INTERVAL_SECONDS="2"
$env:REQUEST_TIMEOUT_SECONDS="1"
$env:PREFER_PRIMARY="true"
uvicorn app:app --port 8000
```

---

## Lancer l’application — Option B (Bash / Linux/macOS/WSL/Git Bash)

### Terminal 1 — Service A

```bash
cd service
export SERVICE_NAME="Service A"
uvicorn app:app --port 8001
```

### Terminal 2 — Service B

```bash
cd service
export SERVICE_NAME="Service B"
uvicorn app:app --port 8002
```

### Terminal 3 — Supervisor / Router

```bash
cd superviseur
export PRIMARY_URL="http://localhost:8001"
export SECONDARY_URL="http://localhost:8002"
export HEALTH_INTERVAL_SECONDS="2"
export REQUEST_TIMEOUT_SECONDS="1"
export PREFER_PRIMARY="true"
uvicorn app:app --port 8000
```

---

## 🧾 Conclusion

Cette preuve de concept illustre comment des **tactiques de disponibilité simples**; détection de défaillance et redondance avec basculement peuvent être intégrées dans une architecture web afin d’améliorer la **résilience** face aux pannes, tout en permettant une **mesure objective** de leur efficacité à l’aide de métriques précises.

```
