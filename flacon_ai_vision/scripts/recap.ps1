# Créer le répertoire admin
$adminDir = "frontend/admin"
if (-not (Test-Path $adminDir)) {
    New-Item -ItemType Directory -Path $adminDir -Force
    Write-Host "✅ Créé dossier: $adminDir"
}

# ============================================
# 1. index.html - Dashboard Complet (Page d'accueil)
# ============================================
$indexHTML = @'
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Falcon AI Vision - Dashboard Admin</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="stylesheet" href="/static/dashboard.css">
    <style>
        .admin-dashboard {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            padding: 20px;
        }
        
        .dashboard-card {
            background: #fff;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            transition: transform 0.3s ease;
        }
        
        .dashboard-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        }
        
        .card-title {
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 15px;
            color: #333;
        }
        
        .card-value {
            font-size: 32px;
            font-weight: 700;
            color: #0066cc;
            margin: 10px 0;
        }
        
        .card-subtitle {
            font-size: 14px;
            color: #666;
        }
        
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
        }
        
        .status-online { background-color: #4CAF50; }
        .status-offline { background-color: #f44336; }
        .status-unknown { background-color: #FF9800; }
        
        .quick-actions {
            display: flex;
            gap: 10px;
            margin-top: 15px;
            flex-wrap: wrap;
        }
        
        .btn-action {
            padding: 8px 12px;
            font-size: 12px;
            background: #0066cc;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            transition: background 0.3s;
        }
        
        .btn-action:hover {
            background: #0052a3;
        }
        
        .health-bar {
            width: 100%;
            height: 8px;
            background: #e0e0e0;
            border-radius: 4px;
            margin: 10px 0;
            overflow: hidden;
        }
        
        .health-bar-fill {
            height: 100%;
            background: linear-gradient(90deg, #4CAF50, #45a049);
            transition: width 0.3s;
        }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="navbar-brand">Falcon AI Vision - Dashboard</div>
        <div class="navbar-menu">
            <a href="index.html" class="nav-link active">📊 Dashboard</a>
            <a href="dashboard-realtime.html" class="nav-link">🎥 Temps Réel</a>
            <a href="cameras.html" class="nav-link">📹 Caméras</a>
            <a href="events.html" class="nav-link">📋 Événements</a>
            <a href="facial.html" class="nav-link">👤 Facial</a>
            <a href="vehicles.html" class="nav-link">🚗 Véhicules</a>
            <a href="users.html" class="nav-link">👥 Utilisateurs</a>
            <a href="#" class="nav-link" id="logoutBtn">🔒 Déconnexion</a>
        </div>
    </div>

    <div class="admin-dashboard">
        <!-- Santé globale -->
        <div class="dashboard-card">
            <div class="card-title">Santé du Système</div>
            <div class="card-value" id="healthPercentage">-</div>
            <div class="health-bar">
                <div class="health-bar-fill" id="healthBar" style="width: 0%"></div>
            </div>
            <div class="card-subtitle" id="healthStatus">Chargement...</div>
            <div class="quick-actions">
                <button class="btn-action" onclick="testAllCameras()">Tester tout</button>
                <button class="btn-action" onclick="refreshHealth()">🔄 Rafraîchir</button>
            </div>
        </div>

        <!-- Caméras en ligne -->
        <div class="dashboard-card">
            <div class="card-title"><span class="status-indicator status-online"></span> Caméras en Ligne</div>
            <div class="card-value" id="onlineCount">-</div>
            <div class="card-subtitle" id="onlineStatus">Chargement...</div>
            <div class="quick-actions">
                <button class="btn-action" onclick="navigateTo('cameras.html')">📹 Gérer</button>
            </div>
        </div>

        <!-- Caméras hors ligne -->
        <div class="dashboard-card">
            <div class="card-title"><span class="status-indicator status-offline"></span> Caméras Hors Ligne</div>
            <div class="card-value" id="offlineCount">-</div>
            <div class="card-subtitle" id="offlineStatus">Chargement...</div>
            <div class="quick-actions">
                <button class="btn-action" onclick="showOfflineCameras()">🔍 Détails</button>
            </div>
        </div>

        <!-- Événements récents -->
        <div class="dashboard-card">
            <div class="card-title">📋 Événements (24h)</div>
            <div class="card-value" id="eventCount">-</div>
            <div class="card-subtitle">Dernière mise à jour: <span id="lastEventTime">-</span></div>
            <div class="quick-actions">
                <button class="btn-action" onclick="navigateTo('events.html')">📋 Voir tous</button>
            </div>
        </div>

        <!-- Utilisateurs actifs -->
        <div class="dashboard-card">
            <div class="card-title">👥 Utilisateurs Actifs</div>
            <div class="card-value" id="activeUsers">-</div>
            <div class="card-subtitle">Utilisateurs enregistrés</div>
            <div class="quick-actions">
                <button class="btn-action" onclick="navigateTo('users.html')">👥 Gérer</button>
            </div>
        </div>

        <!-- Reconnaissance faciale -->
        <div class="dashboard-card">
            <div class="card-title">👤 Reconnaissance Faciale</div>
            <div class="card-value" id="faceCount">-</div>
            <div class="card-subtitle">Visages enregistrés</div>
            <div class="quick-actions">
                <button class="btn-action" onclick="navigateTo('facial.html')">👤 Gérer</button>
                <button class="btn-action" onclick="trainFaceModel()">🧠 Entraîner</button>
            </div>
        </div>

        <!-- Détection de véhicules -->
        <div class="dashboard-card">
            <div class="card-title">🚗 Détection Véhicules</div>
            <div class="card-value" id="vehicleCount">-</div>
            <div class="card-subtitle">Véhicules détectés (24h)</div>
            <div class="quick-actions">
                <button class="btn-action" onclick="navigateTo('vehicles.html')">🚗 Consulter</button>
            </div>
        </div>

        <!-- Stockage -->
        <div class="dashboard-card">
            <div class="card-title">💾 Espace Disque</div>
            <div class="card-value" id="storageUsed">-</div>
            <div class="health-bar">
                <div class="health-bar-fill" id="storageBar" style="width: 0%; background: #FF9800;"></div>
            </div>
            <div class="card-subtitle" id="storageStatus">Chargement...</div>
        </div>
    </div>

    <script>
        // Vérifier authentification
        if (!localStorage.getItem('falcon_ai_vision_token')) {
            window.location.href = '/login.html';
        }
        
        // Configuration API
        const API_BASE_URL = window.location.origin + '/api';
        
        // Charger les données au démarrage
        window.addEventListener('load', () => {
            loadDashboardData();
            setInterval(loadDashboardData, 30000); // Rafraîchir toutes les 30s
        });

        async function loadDashboardData() {
            const token = localStorage.getItem('falcon_ai_vision_token');
            if (!token) return;
            
            const headers = {'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json'};
            
            try {
                // 1. CAMÉRAS
                const camerasRes = await fetch(`${API_BASE_URL}/cameras?skip=0&limit=100`, {headers});
                const cameras = await camerasRes.json();
                
                const totalCameras = Array.isArray(cameras) ? cameras.length : 0;
                const onlineCameras = Array.isArray(cameras) ? cameras.filter(c => c.is_active === true).length : 0;
                const offlineCameras = totalCameras - onlineCameras;
                const healthPercentage = totalCameras > 0 ? Math.round((onlineCameras / totalCameras) * 100) : 0;
                
                document.getElementById('healthPercentage').textContent = healthPercentage + '%';
                document.getElementById('healthBar').style.width = healthPercentage + '%';
                document.getElementById('onlineCount').textContent = onlineCameras;
                document.getElementById('offlineCount').textContent = offlineCameras;
                document.getElementById('onlineStatus').textContent = `sur ${totalCameras} total`;
                document.getElementById('offlineStatus').textContent = `sur ${totalCameras} total`;
                
                // 2. ÉVÉNEMENTS
                const eventsRes = await fetch(`${API_BASE_URL}/events/recent?hours=24`, {headers});
                const eventsData = await eventsRes.json();
                const eventCount = Array.isArray(eventsData) ? eventsData.length : 0;
                
                document.getElementById('eventCount').textContent = eventCount;
                document.getElementById('lastEventTime').textContent = new Date().toLocaleTimeString();
                
                // 3. UTILISATEURS
                try {
                    const usersRes = await fetch(`${API_BASE_URL}/admin/users?limit=100`, {headers});
                    const usersData = await usersRes.json();
                    const userCount = Array.isArray(usersData) ? usersData.length : 'N/A';
                    document.getElementById('activeUsers').textContent = userCount;
                } catch { document.getElementById('activeUsers').textContent = 'N/A'; }
                
                // 4. RECONNAISSANCE FACIALE
                try {
                    const facesRes = await fetch(`${API_BASE_URL}/facial/known-faces`, {headers});
                    const facesData = await facesRes.json();
                    const faceCount = Array.isArray(facesData) ? facesData.length : 'N/A';
                    document.getElementById('faceCount').textContent = faceCount;
                } catch { document.getElementById('faceCount').textContent = 'N/A'; }
                
                // 5. VÉHICULES & STOCKAGE (simulé)
                document.getElementById('vehicleCount').textContent = 'N/A';
                document.getElementById('storageUsed').textContent = 'N/A';
                document.getElementById('storageBar').style.width = '0%';
                
            } catch (error) {
                console.error('Erreur dashboard:', error);
            }
        }

        async function testAllCameras() {
            const token = localStorage.getItem('falcon_ai_vision_token');
            if (!token) return;
            
            alert('🔍 Démarrage des tests de connexion...');
            const headers = {'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json'};
            
            try {
                const camerasRes = await fetch(`${API_BASE_URL}/cameras`, {headers});
                const cameras = await camerasRes.json();
                
                if (!Array.isArray(cameras) || cameras.length === 0) {
                    alert('ℹ️ Aucune caméra trouvée');
                    return;
                }
                
                let online = 0, offline = 0;
                
                for (const camera of cameras) {
                    try {
                        const testRes = await fetch(`${API_BASE_URL}/cameras/${camera.id}/test-connection`, {
                            method: 'POST', headers, body: JSON.stringify({})
                        });
                        testRes.ok ? online++ : offline++;
                    } catch { offline++; }
                }
                
                alert(`✅ Tests terminés:\n📊 ${online} caméras en ligne\n📊 ${offline} caméras hors ligne\n📊 ${cameras.length} caméras total`);
                loadDashboardData();
                
            } catch (error) {
                alert('❌ Erreur: ' + error.message);
            }
        }

        function refreshHealth() { loadDashboardData(); }
        function showOfflineCameras() { alert('🔍 Cette fonctionnalité sera disponible prochainement'); }
        function trainFaceModel() { alert('🧠 Entraînement du modèle facial...\nCette fonctionnalité sera disponible prochainement'); }
        function navigateTo(page) { window.location.href = page; }

        document.getElementById('logoutBtn').addEventListener('click', (e) => {
            e.preventDefault();
            if (confirm('Êtes-vous sûr de vouloir vous déconnecter?')) {
                localStorage.removeItem('falcon_ai_vision_token');
                window.location.href = '/login.html';
            }
        });
    </script>
</body>
</html>
'@

Set-Content -Path "$adminDir/index.html" -Value $indexHTML -Encoding UTF8
Write-Host "✅ index.html recréé"

# ============================================
# 2. dashboard.html - Dashboard Simple
# ============================================
$dashboardHTML = @'
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard Simple - Falcon AI Vision</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="stylesheet" href="/static/dashboard.css">
    <style>
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            padding: 20px;
        }
        
        .dashboard-item {
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            text-align: center;
        }
        
        .dashboard-value {
            font-size: 36px;
            font-weight: 700;
            color: #0066cc;
            margin: 15px 0;
        }
        
        .dashboard-label {
            color: #666;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="navbar-brand">Falcon AI Vision</div>
        <div class="navbar-menu">
            <a href="index.html" class="nav-link">Dashboard Complet</a>
            <a href="dashboard.html" class="nav-link active">Dashboard Simple</a>
            <a href="cameras.html" class="nav-link">Caméras</a>
            <a href="#" class="nav-link" id="logoutBtn">Déconnexion</a>
        </div>
    </div>

    <div class="dashboard-grid">
        <div class="dashboard-item">
            <div class="dashboard-label">Caméras en Ligne</div>
            <div class="dashboard-value" id="onlineCount">-</div>
        </div>
        
        <div class="dashboard-item">
            <div class="dashboard-label">Caméras Totales</div>
            <div class="dashboard-value" id="totalCameras">-</div>
        </div>
        
        <div class="dashboard-item">
            <div class="dashboard-label">Santé du Système</div>
            <div class="dashboard-value" id="health">-</div>
        </div>
        
        <div class="dashboard-item">
            <div class="dashboard-label">Événements (24h)</div>
            <div class="dashboard-value" id="eventCount">-</div>
        </div>
    </div>

    <script>
        // Vérifier authentification
        if (!localStorage.getItem('falcon_ai_vision_token')) {
            window.location.href = '/login.html';
        }
        
        // Configuration API
        const API_BASE_URL = window.location.origin + '/api';
        
        // Charger les données au démarrage
        window.addEventListener('load', () => {
            loadDashboard();
            setInterval(loadDashboard, 30000);
        });
        
        async function loadDashboard() {
            const token = localStorage.getItem('falcon_ai_vision_token');
            if (!token) return;
            
            const headers = {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            };
            
            try {
                // 1. Récupérer toutes les caméras
                const camerasRes = await fetch(`${API_BASE_URL}/cameras`, { headers });
                if (!camerasRes.ok) throw new Error(`HTTP ${camerasRes.status}`);
                
                const cameras = await camerasRes.json();
                const totalCameras = Array.isArray(cameras) ? cameras.length : 0;
                const onlineCameras = Array.isArray(cameras) ? 
                    cameras.filter(c => c.is_active === true).length : 0;
                const healthPercentage = totalCameras > 0 ? 
                    Math.round((onlineCameras / totalCameras) * 100) : 0;
                
                // Afficher stats caméras
                document.getElementById('onlineCount').textContent = onlineCameras;
                document.getElementById('totalCameras').textContent = totalCameras;
                document.getElementById('health').textContent = healthPercentage + '%';
                
                // 2. Récupérer événements récents
                try {
                    const eventsRes = await fetch(`${API_BASE_URL}/events/recent?hours=24`, { headers });
                    if (eventsRes.ok) {
                        const events = await eventsRes.json();
                        const eventCount = Array.isArray(events) ? events.length : 0;
                        document.getElementById('eventCount').textContent = eventCount;
                    }
                } catch (e) {
                    console.warn('Erreur chargement événements:', e);
                    document.getElementById('eventCount').textContent = 'N/A';
                }
                
            } catch (error) {
                console.error('Erreur chargement dashboard:', error);
                document.getElementById('onlineCount').textContent = 'Err';
                document.getElementById('totalCameras').textContent = 'Err';
                document.getElementById('health').textContent = 'Err';
                document.getElementById('eventCount').textContent = 'Err';
            }
        }
        
        document.getElementById('logoutBtn').addEventListener('click', (e) => {
            e.preventDefault();
            if (confirm('Êtes-vous sûr de vouloir vous déconnecter?')) {
                localStorage.removeItem('falcon_ai_vision_token');
                window.location.href = '/login.html';
            }
        });
    </script>
</body>
</html>
'@

Set-Content -Path "$adminDir/dashboard.html" -Value $dashboardHTML -Encoding UTF8
Write-Host "✅ dashboard.html recréé"

# ============================================
# 3. dashboard-realtime.html - Dashboard Temps Réel
# ============================================
$realtimeHTML = @'
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard Temps Réel - Falcon AI Vision</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="stylesheet" href="/static/dashboard.css">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            background: #0a0e27;
            color: #e0e0e0;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            height: 100vh;
            overflow: hidden;
        }

        .dashboard-container {
            display: grid;
            grid-template-columns: 1fr;
            grid-template-rows: auto 1fr auto;
            height: 100vh;
            gap: 8px;
            padding: 8px;
        }

        /* ==================== HEADER ==================== */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: linear-gradient(135deg, #1a1f3a 0%, #2d1b4e 100%);
            padding: 12px 16px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
        }

        .header h1 {
            font-size: 20px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .header-controls {
            display: flex;
            gap: 12px;
            align-items: center;
        }

        .status-badge {
            background: #4CAF50;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
        }

        .status-badge.offline {
            background: #f44336;
        }

        button {
            background: #667eea;
            border: none;
            color: white;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            transition: background 0.3s;
        }

        button:hover {
            background: #5568d3;
        }

        /* ==================== MAIN CONTENT ==================== */
        .content {
            display: grid;
            grid-template-columns: 1fr 350px;
            gap: 8px;
        }

        /* ==================== CAMERA GRID ==================== */
        .cameras-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 8px;
            overflow: auto;
            padding: 4px;
        }

        .camera-tile {
            background: #1a1f3a;
            border: 1px solid #667eea;
            border-radius: 8px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.1);
            transition: border-color 0.3s;
        }

        .camera-tile:hover {
            border-color: #7c8ff5;
        }

        .camera-header {
            background: #2d1b4e;
            padding: 8px 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #667eea;
        }

        .camera-name {
            font-weight: 600;
            font-size: 13px;
        }

        .camera-status {
            display: flex;
            gap: 8px;
            font-size: 11px;
        }

        .status-item {
            display: flex;
            align-items: center;
            gap: 4px;
        }

        .status-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: #4CAF50;
        }

        .status-item.recording .status-dot {
            background: #f44336;
            animation: pulse 1s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .camera-stream {
            flex: 1;
            background: #000;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
            aspect-ratio: 16/9;
            overflow: hidden;
        }

        .camera-stream img,
        .camera-stream video {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }

        .stream-placeholder {
            color: #666;
            font-size: 12px;
            text-align: center;
        }

        .camera-stats {
            background: #222835;
            padding: 6px 10px;
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 6px;
            font-size: 11px;
            border-top: 1px solid #667eea;
        }

        .stat {
            text-align: center;
        }

        .stat-value {
            font-weight: 600;
            color: #667eea;
        }

        .stat-label {
            color: #999;
            font-size: 10px;
            margin-top: 2px;
        }

        /* ==================== SIDEBAR ==================== */
        .sidebar {
            display: flex;
            flex-direction: column;
            gap: 8px;
            overflow: auto;
        }

        .panel {
            background: #1a1f3a;
            border: 1px solid #667eea;
            border-radius: 8px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.1);
        }

        .panel-header {
            background: #2d1b4e;
            padding: 10px 12px;
            border-bottom: 1px solid #667eea;
            font-weight: 600;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .panel-content {
            flex: 1;
            overflow: auto;
            padding: 8px;
        }

        /* ==================== ALERTS PANEL ==================== */
        .alerts-list {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .alert-item {
            background: #222835;
            padding: 8px 10px;
            border-left: 3px solid #f44336;
            border-radius: 4px;
            font-size: 11px;
            animation: slideIn 0.3s ease-out;
        }

        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateX(-10px);
            }
            to {
                opacity: 1;
                transform: translateX(0);
            }
        }

        .alert-item.motion { border-left-color: #FFC107; }
        .alert-item.vehicle { border-left-color: #2196F3; }
        .alert-item.person { border-left-color: #00BCD4; }
        .alert-item.face { border-left-color: #FF5722; }
        .alert-item.alarm { border-left-color: #f44336; }

        .alert-time {
            color: #999;
            font-size: 10px;
            margin-top: 2px;
        }

        .alert-message {
            font-weight: 500;
            margin-bottom: 2px;
        }

        .alert-camera {
            color: #667eea;
            font-size: 10px;
        }

        /* ==================== STATS PANEL ==================== */
        .overall-stats {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }

        .big-stat {
            background: #222835;
            padding: 12px;
            border-radius: 6px;
            text-align: center;
        }

        .big-stat-value {
            font-size: 24px;
            font-weight: 700;
            color: #667eea;
        }

        .big-stat-label {
            font-size: 11px;
            color: #999;
            margin-top: 4px;
            text-transform: uppercase;
        }

        /* ==================== FOOTER ==================== */
        .footer {
            background: #1a1f3a;
            border-top: 1px solid #667eea;
            padding: 6px 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 11px;
            color: #999;
        }

        .connection-info {
            display: flex;
            gap: 12px;
        }

        .info-item {
            display: flex;
            align-items: center;
            gap: 4px;
        }

        /* ==================== RESPONSIVE ==================== */
        @media (max-width: 1920px) {
            .content {
                grid-template-columns: 1fr;
            }

            .sidebar {
                max-height: 200px;
            }

            .cameras-grid {
                grid-template-columns: 1fr;
            }

            .camera-tile {
                min-height: 250px;
            }
        }

        .loading {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #667eea;
            animation: blink 1s infinite;
        }

        @keyframes blink {
            0%, 50%, 100% { opacity: 1; }
            25%, 75% { opacity: 0.3; }
        }
    </style>
</head>
<body>
    <div class="dashboard-container">
        <!-- HEADER -->
        <div class="header">
            <h1>🎥 Dashboard Temps Réel</h1>
            <div class="header-controls">
                <span class="status-badge" id="wsStatus">● CONNECTÉ</span>
                <button onclick="toggleFullscreen()">⛶ Plein écran</button>
                <button onclick="location.href='/logout'">Déconnexion</button>
            </div>
        </div>

        <!-- MAIN CONTENT -->
        <div class="content">
            <!-- CAMERA GRID -->
            <div class="cameras-grid" id="camerasGrid">
                <!-- Caméras chargées dynamiquement -->
            </div>

            <!-- SIDEBAR -->
            <div class="sidebar">
                <!-- ALERTS PANEL -->
                <div class="panel" style="flex: 1.5;">
                    <div class="panel-header">🚨 Alertes Temps Réel</div>
                    <div class="panel-content">
                        <div class="alerts-list" id="alertsList">
                            <div style="color: #999; text-align: center; margin-top: 20px;">
                                Aucune alerte
                            </div>
                        </div>
                    </div>
                </div>

                <!-- STATS PANEL -->
                <div class="panel">
                    <div class="panel-header">📊 Statistiques</div>
                    <div class="panel-content">
                        <div class="overall-stats">
                            <div class="big-stat">
                                <div class="big-stat-value" id="totalDetections">0</div>
                                <div class="big-stat-label">Détections</div>
                            </div>
                            <div class="big-stat">
                                <div class="big-stat-value" id="activeAlerts">0</div>
                                <div class="big-stat-label">Alertes</div>
                            </div>
                            <div class="big-stat">
                                <div class="big-stat-value" id="avgFps">0</div>
                                <div class="big-stat-label">FPS Moy</div>
                            </div>
                            <div class="big-stat">
                                <div class="big-stat-value" id="streamHealth">100%</div>
                                <div class="big-stat-label">Santé</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- FOOTER -->
        <div class="footer">
            <div class="connection-info">
                <div class="info-item">
                    WebSocket: <span id="wsUrl">wss://localhost:5000</span>
                </div>
                <div class="info-item">
                    Caméras: <span id="cameraCount">0</span>
                </div>
                <div class="info-item">
                    Heure: <span id="currentTime">--:--:--</span>
                </div>
            </div>
            <div class="info-item">
                <div class="loading"></div> Synchronisation en cours...
            </div>
        </div>
    </div>

    <script>
        // Vérifier authentification
        if (!localStorage.getItem('falcon_ai_vision_token')) {
            window.location.href = '/login.html';
        }
        
        // Configuration API
        const API_BASE_URL = window.location.origin + '/api';
        
        // Charger les données au démarrage
        window.addEventListener('load', () => {
            updateTime();
            setInterval(updateTime, 1000);
            loadCameras();
        });

        // ==================== CAMERA MANAGEMENT ====================
        async function loadCameras() {
            try {
                const token = localStorage.getItem('falcon_ai_vision_token');
                const response = await fetch(`${API_BASE_URL}/cameras`, {
                    headers: {'Authorization': `Bearer ${token}`}
                });
                const cameras = await response.json();
                
                const grid = document.getElementById('camerasGrid');
                grid.innerHTML = '';
                
                cameras.forEach(camera => {
                    const tile = document.createElement('div');
                    tile.className = 'camera-tile';
                    tile.innerHTML = `
                        <div class="camera-header">
                            <div class="camera-name">${camera.name || 'Caméra ' + camera.id}</div>
                            <div class="camera-status">
                                <div class="status-item ${camera.is_active ? 'recording' : ''}">
                                    <div class="status-dot"></div>
                                    <span>${camera.is_active ? 'ACTIVE' : 'OFFLINE'}</span>
                                </div>
                            </div>
                        </div>
                        <div class="camera-stream">
                            ${camera.is_active ? 
                                `<img src="/api/cameras/${camera.id}/stream" alt="${camera.name}" 
                                      onerror="this.onerror=null;this.src='data:image/svg+xml,<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"320\" height=\"180\"><rect width=\"100%\" height=\"100%\" fill=\"%231a1f3a\"/><text x=\"50%\" y=\"50%\" text-anchor=\"middle\" dy=\".3em\" fill=\"%23667eea\" font-family=\"sans-serif\">FLUX ${camera.name}</text></svg>'" 
                                      style="width:100%;height:100%;object-fit:cover;">` :
                                `<div class="stream-placeholder" style="color:#f44336;">HORS LIGNE</div>`
                            }
                        </div>
                        <div class="camera-stats">
                            <div class="stat">
                                <div class="stat-value" id="fps-${camera.id}">${camera.is_active ? '15' : '0'}</div>
                                <div class="stat-label">FPS</div>
                            </div>
                            <div class="stat">
                                <div class="stat-value" id="detections-${camera.id}">0</div>
                                <div class="stat-label">Détections</div>
                            </div>
                            <div class="stat">
                                <div class="stat-value" id="confidence-${camera.id}">${camera.is_active ? '85%' : '0%'}</div>
                                <div class="stat-label">Confiance</div>
                            </div>
                        </div>
                    `;
                    grid.appendChild(tile);
                });
                
                document.getElementById('cameraCount').textContent = cameras.length;
                
            } catch (error) {
                console.error('Erreur chargement caméras:', error);
            }
        }

        // ==================== UTILITIES ====================
        function updateTime() {
            const now = new Date();
            document.getElementById('currentTime').textContent = 
                now.toLocaleTimeString('fr-FR');
        }

        function toggleFullscreen() {
            if (!document.fullscreenElement) {
                document.documentElement.requestFullscreen().catch(err => {
                    console.error(`Erreur fullscreen: ${err.message}`);
                });
            } else {
                document.exitFullscreen();
            }
        }

        // Gérer la déconnexion
        document.querySelector('button[onclick*="logout"]').onclick = function(e) {
            e.preventDefault();
            localStorage.removeItem('falcon_ai_vision_token');
            window.location.href = '/login.html';
        };
        
        // Mettre à jour l'URL WebSocket (pour affichage seulement)
        document.getElementById('wsUrl').textContent = window.location.host;
    </script>
</body>
</html>
'@

Set-Content -Path "$adminDir/dashboard-realtime.html" -Value $realtimeHTML -Encoding UTF8
Write-Host "✅ dashboard-realtime.html recréé"

# ============================================
# 4. cameras.html - Gestion Caméras
# ============================================
$camerasHTML = @'
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gestion des Caméras - Falcon AI Vision</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="stylesheet" href="/static/dashboard.css">
    <style>
        .status-badge {
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: bold;
        }
        .status-online {
            background-color: #4CAF50;
            color: white;
        }
        .status-offline {
            background-color: #f44336;
            color: white;
        }
        .btn-action {
            padding: 4px 8px;
            margin: 2px;
            background: #0066cc;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }
        .btn-delete {
            background: #f44336;
        }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="navbar-brand">Falcon AI Vision - Gestion des Caméras</div>
        <div class="navbar-menu">
            <a href="index.html" class="nav-link">Dashboard</a>
            <a href="dashboard-realtime.html" class="nav-link">Temps Réel</a>
            <a href="cameras.html" class="nav-link active">Caméras</a>
            <a href="events.html" class="nav-link">Événements</a>
            <a href="facial.html" class="nav-link">Facial</a>
            <a href="vehicles.html" class="nav-link">Véhicules</a>
            <a href="users.html" class="nav-link">Utilisateurs</a>
            <a href="#" class="nav-link" id="logoutBtn">Déconnexion</a>
        </div>
    </div>

    <div class="container" style="padding: 20px;">
        <div class="header">
            <h1>Gestion des Caméras</h1>
            <button class="btn-primary" onclick="showAddCameraForm()">+ Ajouter Caméra</button>
        </div>

        <div class="filters">
            <input type="text" id="searchInput" placeholder="Rechercher une caméra..." onkeyup="filterCameras()">
            <select id="statusFilter" onchange="filterCameras()">
                <option value="">Tous les statuts</option>
                <option value="connected">En ligne</option>
                <option value="disconnected">Hors ligne</option>
                <option value="unknown">Inconnu</option>
            </select>
            <button class="btn-secondary" onclick="testAllCameras()">Tester tout</button>
        </div>

        <table class="cameras-table" id="camerasTable">
            <thead>
                <tr>
                    <th>Caméra</th>
                    <th>Adresse IP</th>
                    <th>Port</th>
                    <th>Statut</th>
                    <th>Dernière Vérification</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody id="camerasBody">
                <tr><td colspan="6">Chargement...</td></tr>
            </tbody>
        </table>
    </div>

    <!-- Modal Ajout Caméra -->
    <div id="addCameraModal" class="modal" style="display: none;">
        <div class="modal-content">
            <span class="close" onclick="closeModal('addCameraModal')">&times;</span>
            <h2>Ajouter une Caméra</h2>
            <form onsubmit="addCamera(event)">
                <input type="text" id="cameraName" placeholder="Nom de la caméra" required>
                <input type="text" id="cameraIp" placeholder="Adresse IP" required>
                <input type="number" id="cameraPort" placeholder="Port (défaut: 554)" value="554">
                <input type="text" id="cameraUrl" placeholder="URL RTSP (optionnel)">
                <button type="submit">Ajouter</button>
            </form>
        </div>
    </div>

    <script>
        const TOKEN_KEY = 'falcon_ai_vision_token';
        const API_BASE_URL = window.location.origin + '/api';
        
        // Vérifier authentification
        if (!localStorage.getItem(TOKEN_KEY)) {
            window.location.href = '/login.html';
        }
        
        window.addEventListener('load', loadCameras);

        async function loadCameras() {
            const token = localStorage.getItem(TOKEN_KEY);
            if (!token) return;
            
            try {
                const response = await fetch(`${API_BASE_URL}/cameras`, {
                    headers: {'Authorization': `Bearer ${token}`}
                });
                
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                
                const cameras = await response.json();
                const tbody = document.getElementById('camerasBody');
                tbody.innerHTML = '';
                
                if (!Array.isArray(cameras) || cameras.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6">Aucune caméra configurée</td></tr>';
                    return;
                }
                
                cameras.forEach(camera => {
                    const row = document.createElement('tr');
                    const isOnline = camera.is_active === true;
                    const statusClass = isOnline ? 'status-online' : 'status-offline';
                    const statusText = isOnline ? 'En ligne' : 'Hors ligne';
                    
                    row.innerHTML = `
                        <td>${camera.name || 'Sans nom'}</td>
                        <td>${camera.ip_address || 'N/A'}</td>
                        <td>${camera.port || 554}</td>
                        <td><span class="status-badge ${statusClass}">${statusText}</span></td>
                        <td>${camera.last_check || 'Jamais'}</td>
                        <td>
                            <button class="btn-action" onclick="testCamera(${camera.id})">Tester</button>
                            <button class="btn-action" onclick="editCamera(${camera.id})">Éditer</button>
                            <button class="btn-action btn-delete" onclick="deleteCamera(${camera.id})">Supprimer</button>
                        </td>
                    `;
                    tbody.appendChild(row);
                });
                
            } catch (error) {
                console.error('Erreur chargement caméras:', error);
                document.getElementById('camerasBody').innerHTML = 
                    '<tr><td colspan="6">Erreur de chargement: ' + error.message + '</td></tr>';
            }
        }

        function showAddCameraForm() {
            document.getElementById('addCameraModal').style.display = 'block';
        }

        function closeModal(modalId) {
            document.getElementById(modalId).style.display = 'none';
            const form = document.getElementById('addCameraModal').querySelector('form');
            if (form) form.reset();
        }

        async function addCamera(event) {
            event.preventDefault();
            
            const token = localStorage.getItem(TOKEN_KEY);
            if (!token) return;
            
            const cameraData = {
                name: document.getElementById('cameraName').value,
                ip_address: document.getElementById('cameraIp').value,
                port: parseInt(document.getElementById('cameraPort').value) || 554,
                rtsp_url: document.getElementById('cameraUrl').value || 
                         `rtsp://${document.getElementById('cameraIp').value}:${document.getElementById('cameraPort').value || 554}/stream`,
                is_active: true,
                streaming_enabled: true,
                motion_detection_enabled: false,
                object_detection_enabled: false
            };
            
            try {
                const response = await fetch(`${API_BASE_URL}/cameras`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(cameraData)
                });
                
                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Erreur inconnue');
                }
                
                const result = await response.json();
                alert('✅ Caméra ajoutée avec succès! ID: ' + result.id);
                closeModal('addCameraModal');
                loadCameras();
                
            } catch (error) {
                alert('❌ Erreur: ' + error.message);
            }
        }

        async function testCamera(cameraId) {
            const token = localStorage.getItem(TOKEN_KEY);
            if (!token) return;
            
            try {
                const response = await fetch(`${API_BASE_URL}/cameras/${cameraId}/test-connection`, {
                    method: 'POST',
                    headers: {'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json'},
                    body: JSON.stringify({})
                });
                
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                
                const result = await response.json();
                
                if (result.success) {
                    alert(`✅ Caméra ${cameraId}: Connectée avec succès\nMessage: ${result.message || 'OK'}`);
                } else {
                    alert(`❌ Caméra ${cameraId}: Échec de connexion\nMessage: ${result.message || 'Erreur'}`);
                }
                
                loadCameras();
                
            } catch (error) {
                alert('❌ Erreur de test: ' + error.message);
            }
        }

        async function testAllCameras() {
            const token = localStorage.getItem(TOKEN_KEY);
            if (!token) return;
            
            alert('🔍 Test de toutes les caméras en cours...');
            const headers = {'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json'};
            
            try {
                const camerasRes = await fetch(`${API_BASE_URL}/cameras`, { headers });
                const cameras = await camerasRes.json();
                
                if (!Array.isArray(cameras) || cameras.length === 0) {
                    alert('ℹ️ Aucune caméra à tester');
                    return;
                }
                
                let online = 0, offline = 0, tested = 0;
                
                for (const camera of cameras) {
                    try {
                        const testRes = await fetch(`${API_BASE_URL}/cameras/${camera.id}/test-connection`, {
                            method: 'POST', headers, body: JSON.stringify({})
                        });
                        
                        if (testRes.ok) {
                            const testResult = await testRes.json();
                            if (testResult.success) online++; else offline++;
                        } else offline++;
                        
                        tested++;
                        
                    } catch { offline++; tested++; }
                }
                
                alert(`📊 Résultats:\n✅ ${online} caméras en ligne\n❌ ${offline} caméras hors ligne\n📋 ${cameras.length} total`);
                loadCameras();
                
            } catch (error) {
                alert('❌ Erreur: ' + error.message);
            }
        }

        function editCamera(cameraId) {
            alert(`Édition caméra ${cameraId} - À implémenter`);
        }

        async function deleteCamera(cameraId) {
            if (!confirm('⚠️ Êtes-vous sûr de vouloir supprimer cette caméra?')) return;
            
            const token = localStorage.getItem(TOKEN_KEY);
            if (!token) return;
            
            try {
                const response = await fetch(`${API_BASE_URL}/cameras/${cameraId}`, {
                    method: 'DELETE',
                    headers: {'Authorization': `Bearer ${token}`}
                });
                
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                
                alert('✅ Caméra supprimée');
                loadCameras();
                
            } catch (error) {
                alert('❌ Erreur: ' + error.message);
            }
        }

        function filterCameras() {
            const searchTerm = document.getElementById('searchInput').value.toLowerCase();
            const statusFilter = document.getElementById('statusFilter').value;
            
            const rows = document.getElementById('camerasTable').getElementsByTagName('tbody')[0].rows;
            
            for (let row of rows) {
                if (row.cells.length < 4) continue;
                
                const name = row.cells[0].textContent.toLowerCase();
                const statusElement = row.cells[3].querySelector('.status-badge');
                const status = statusElement ? statusElement.textContent.toLowerCase() : '';
                
                let matchesStatus = true;
                if (statusFilter === 'connected') matchesStatus = status.includes('en ligne');
                else if (statusFilter === 'disconnected') matchesStatus = status.includes('hors ligne');
                
                const matchesSearch = name.includes(searchTerm);
                row.style.display = matchesSearch && matchesStatus ? '' : 'none';
            }
        }

        document.getElementById('logoutBtn').addEventListener('click', (e) => {
            e.preventDefault();
            if (confirm('Êtes-vous sûr de vouloir vous déconnecter?')) {
                localStorage.removeItem(TOKEN_KEY);
                window.location.href = '/login.html';
            }
        });
    </script>
</body>
</html>
'@

Set-Content -Path "$adminDir/cameras.html" -Value $camerasHTML -Encoding UTF8
Write-Host "✅ cameras.html recréé"

# ============================================
# 5. events.html - Événements
# ============================================
$eventsHTML = @'
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Événements - Falcon AI Vision</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="stylesheet" href="/static/dashboard.css">
    <style>
        .event-badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }
        
        .event-badge.motion { background: #FFC107; color: #000; }
        .event-badge.face { background: #00BCD4; color: white; }
        .event-badge.vehicle { background: #2196F3; color: white; }
        .event-badge.connection { background: #4CAF50; color: white; }
        .event-badge.alarm { background: #f44336; color: white; }
        .event-badge.object { background: #9C27B0; color: white; }
        .event-badge.person { background: #3F51B5; color: white; }
        
        .btn-action {
            padding: 4px 8px;
            background: #0066cc;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
            margin: 2px;
        }
        
        .severity-low { color: #4CAF50; }
        .severity-medium { color: #FF9800; }
        .severity-high { color: #f44336; }
        
        .filters {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        
        .filters input, .filters select {
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            min-width: 150px;
        }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="navbar-brand">Falcon AI Vision - Événements</div>
        <div class="navbar-menu">
            <a href="index.html" class="nav-link">Dashboard</a>
            <a href="dashboard-realtime.html" class="nav-link">Temps Réel</a>
            <a href="cameras.html" class="nav-link">Caméras</a>
            <a href="events.html" class="nav-link active">Événements</a>
            <a href="facial.html" class="nav-link">Facial</a>
            <a href="vehicles.html" class="nav-link">Véhicules</a>
            <a href="users.html" class="nav-link">Utilisateurs</a>
            <a href="#" class="nav-link" id="logoutBtn">Déconnexion</a>
        </div>
    </div>

    <div class="container" style="padding: 20px; max-width: 1400px; margin: 0 auto;">
        <div class="header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px;">
            <h1>📋 Journal des Événements</h1>
            <div style="display: flex; gap: 10px;">
                <button class="btn-secondary" onclick="refreshEvents()">🔄 Rafraîchir</button>
                <button class="btn-secondary" onclick="exportEvents()">📥 Exporter</button>
            </div>
        </div>

        <div class="filters">
            <input type="text" id="searchInput" placeholder="Rechercher..." 
                   onkeyup="filterEvents()" style="flex: 1;">
            <select id="typeFilter" onchange="filterEvents()">
                <option value="">Tous types</option>
                <option value="motion">Mouvement</option>
                <option value="person">Personne</option>
                <option value="vehicle">Véhicule</option>
                <option value="object">Objet</option>
                <option value="face">Visage</option>
                <option value="alarm">Alarme</option>
                <option value="connection">Connexion</option>
            </select>
            <select id="severityFilter" onchange="filterEvents()">
                <option value="">Toutes sévérités</option>
                <option value="info">Info</option>
                <option value="warning">Warning</option>
                <option value="critical">Critique</option>
            </select>
            <select id="periodFilter" onchange="loadEventsByPeriod()">
                <option value="1">Dernière heure</option>
                <option value="24" selected>Dernières 24h</option>
                <option value="168">7 derniers jours</option>
                <option value="720">30 derniers jours</option>
                <option value="all">Tous</option>
            </select>
        </div>

        <table id="eventsTable">
            <thead>
                <tr>
                    <th>Date/Heure</th>
                    <th>Type</th>
                    <th>Sévérité</th>
                    <th>Caméra</th>
                    <th>Description</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody id="eventsBody">
                <tr><td colspan="6" style="padding: 40px; text-align: center;">Chargement...</td></tr>
            </tbody>
        </table>

        <div style="margin-top: 20px; padding: 15px; background: #f8f9fa; border-radius: 4px; display: flex; justify-content: space-between;">
            <div>
                <strong>Total:</strong> <span id="eventCount">0</span> événements |
                <strong>Filtré:</strong> <span id="filteredCount">0</span>
            </div>
            <div>
                <button class="btn-secondary" onclick="previousPage()" id="prevBtn" disabled>◀ Précédent</button>
                <span style="margin: 0 10px;">Page <span id="currentPage">1</span></span>
                <button class="btn-secondary" onclick="nextPage()" id="nextBtn" disabled>Suivant ▶</button>
            </div>
        </div>
    </div>

    <script>
        const TOKEN_KEY = 'falcon_ai_vision_token';
        const API_BASE_URL = window.location.origin + '/api';
        
        let currentEvents = [];
        let filteredEvents = [];
        let currentPage = 1;
        const pageSize = 50;
        
        window.addEventListener('load', () => {
            if (!localStorage.getItem(TOKEN_KEY)) {
                window.location.href = '/login.html';
                return;
            }
            loadEvents();
        });
        
        async function loadEvents() {
            const token = localStorage.getItem(TOKEN_KEY);
            if (!token) return;
            
            const period = document.getElementById('periodFilter').value;
            const url = period === 'all' 
                ? `${API_BASE_URL}/events?skip=0&limit=500`
                : `${API_BASE_URL}/events/recent?hours=${period}`;
            
            try {
                const response = await fetch(url, {
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    }
                });
                
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                
                const events = await response.json();
                currentEvents = Array.isArray(events) ? events : [];
                
                updateEventCount();
                filterEvents();
                
            } catch (error) {
                console.error('Erreur:', error);
                document.getElementById('eventsBody').innerHTML = 
                    '<tr><td colspan="6" style="padding: 40px; text-align: center; color: #f44336;">Erreur: ' + error.message + '</td></tr>';
            }
        }
        
        function renderEvents() {
            const tbody = document.getElementById('eventsBody');
            const startIndex = (currentPage - 1) * pageSize;
            const endIndex = startIndex + pageSize;
            const pageEvents = filteredEvents.slice(startIndex, endIndex);
            
            if (pageEvents.length === 0) {
                tbody.innerHTML = 
                    '<tr><td colspan="6" style="padding: 40px; text-align: center; color: #666;">Aucun événement</td></tr>';
                return;
            }
            
            tbody.innerHTML = pageEvents.map(event => {
                const timestamp = event.detected_at || event.created_at;
                const date = timestamp ? new Date(timestamp).toLocaleString('fr-FR') : '-';
                const type = event.event_type || 'unknown';
                const severity = event.severity || 'info';
                const cameraId = event.camera_id || '-';
                const description = event.description || 'Événement détecté';
                const confidence = event.confidence ? Math.round(event.confidence * 100) + '%' : '';
                
                return `
                    <tr>
                        <td>${date}</td>
                        <td>
                            <span class="event-badge ${type}">${type}</span>
                            ${confidence ? `<br><small>${confidence}</small>` : ''}
                        </td>
                        <td class="severity-${severity}">${severity.toUpperCase()}</td>
                        <td>Caméra ${cameraId}</td>
                        <td>${description}</td>
                        <td>
                            <button class="btn-action" onclick="viewEventDetails(${event.id})">👁️ Voir</button>
                            ${event.acknowledged !== true ? 
                                `<button class="btn-action" onclick="acknowledgeEvent(${event.id})" style="background: #4CAF50;">✓ Reconnaître</button>` : 
                                '<small style="color: #4CAF50;">✓ Reconnu</small>'
                            }
                        </td>
                    </tr>
                `;
            }).join('');
            
            updatePagination();
        }
        
        function filterEvents() {
            const searchTerm = document.getElementById('searchInput').value.toLowerCase();
            const typeFilter = document.getElementById('typeFilter').value;
            const severityFilter = document.getElementById('severityFilter').value;
            
            filteredEvents = currentEvents.filter(event => {
                const matchesSearch = !searchTerm || 
                    (event.description && event.description.toLowerCase().includes(searchTerm)) ||
                    (event.event_type && event.event_type.toLowerCase().includes(searchTerm));
                
                const matchesType = !typeFilter || event.event_type === typeFilter;
                const matchesSeverity = !severityFilter || event.severity === severityFilter;
                
                return matchesSearch && matchesType && matchesSeverity;
            });
            
            currentPage = 1;
            updateEventCount();
            renderEvents();
        }
        
        function updateEventCount() {
            document.getElementById('eventCount').textContent = currentEvents.length;
            document.getElementById('filteredCount').textContent = filteredEvents.length;
        }
        
        function updatePagination() {
            const totalPages = Math.ceil(filteredEvents.length / pageSize);
            document.getElementById('currentPage').textContent = currentPage;
            
            const prevBtn = document.getElementById('prevBtn');
            const nextBtn = document.getElementById('nextBtn');
            
            prevBtn.disabled = currentPage <= 1;
            nextBtn.disabled = currentPage >= totalPages || totalPages === 0;
        }
        
        function previousPage() {
            if (currentPage > 1) {
                currentPage--;
                renderEvents();
            }
        }
        
        function nextPage() {
            const totalPages = Math.ceil(filteredEvents.length / pageSize);
            if (currentPage < totalPages) {
                currentPage++;
                renderEvents();
            }
        }
        
        async function viewEventDetails(eventId) {
            const token = localStorage.getItem(TOKEN_KEY);
            if (!token) return;
            
            try {
                const response = await fetch(`${API_BASE_URL}/events/${eventId}`, {
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    }
                });
                
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                
                const event = await response.json();
                const details = `
                    <strong>ID:</strong> ${event.id}<br>
                    <strong>Type:</strong> ${event.event_type}<br>
                    <strong>Sévérité:</strong> ${event.severity}<br>
                    <strong>Caméra ID:</strong> ${event.camera_id}<br>
                    <strong>Date:</strong> ${new Date(event.detected_at || event.created_at).toLocaleString('fr-FR')}<br>
                    <strong>Description:</strong> ${event.description || 'N/A'}<br>
                    <strong>Confiance:</strong> ${event.confidence ? Math.round(event.confidence * 100) + '%' : 'N/A'}
                `;
                
                alert('📋 Détails Événement #' + eventId + '\n\n' + details);
                
            } catch (error) {
                alert('❌ Erreur: ' + error.message);
            }
        }
        
        async function acknowledgeEvent(eventId) {
            const token = localStorage.getItem(TOKEN_KEY);
            if (!token || !confirm('Marquer comme reconnu?')) return;
            
            try {
                const response = await fetch(`${API_BASE_URL}/events/${eventId}/acknowledge`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    }
                });
                
                if (response.ok) {
                    alert('✅ Événement marqué comme reconnu');
                    loadEvents();
                } else throw new Error(`HTTP ${response.status}`);
                
            } catch (error) {
                alert('❌ Erreur: ' + error.message);
            }
        }
        
        function exportEvents() {
            if (filteredEvents.length === 0) {
                alert('Aucun événement à exporter');
                return;
            }
            
            const headers = ['Date', 'Type', 'Sévérité', 'Caméra', 'Description', 'Confiance'];
            const csvRows = [
                headers.join(','),
                ...filteredEvents.map(event => [
                    new Date(event.detected_at || event.created_at).toISOString(),
                    event.event_type || '',
                    event.severity || '',
                    event.camera_id || '',
                    `"${(event.description || '').replace(/"/g, '""')}"`,
                    event.confidence || ''
                ].join(','))
            ];
            
            const csvContent = csvRows.join('\n');
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `evenements_${new Date().toISOString().split('T')[0]}.csv`;
            link.click();
            URL.revokeObjectURL(url);
            
            alert(`✅ ${filteredEvents.length} événements exportés`);
        }
        
        function refreshEvents() {
            currentPage = 1;
            loadEvents();
        }
        
        function loadEventsByPeriod() {
            currentPage = 1;
            loadEvents();
        }
        
        document.getElementById('logoutBtn').addEventListener('click', (e) => {
            e.preventDefault();
            if (confirm('Êtes-vous sûr de vouloir vous déconnecter?')) {
                localStorage.removeItem(TOKEN_KEY);
                window.location.href = '/login.html';
            }
        });
    </script>
</body>
</html>
'@

Set-Content -Path "$adminDir/events.html" -Value $eventsHTML -Encoding UTF8
Write-Host "✅ events.html recréé"

Write-Host "`n=== CRÉATION EN COURS ==="
Write-Host "✅ 5 fichiers sur 8 créés..."
Write-Host "Continuez ? (O/N)"
$response = Read-Host
if ($response -ne 'O') { exit }

# ============================================
# 6. facial.html - Reconnaissance Faciale
# ============================================
Write-Host "Création facial.html..."
# [Code facial.html ici - message trop long, continuation dans prochain message]