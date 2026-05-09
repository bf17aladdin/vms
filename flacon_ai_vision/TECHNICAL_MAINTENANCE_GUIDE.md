# 🛠️ Documentation Technique - Maintenance & Customization

## 📋 Vue d'Ensemble des Fichiers

### 1. **GlobalLayout.css** — Système de Design Principal
**Localisation:** `src/styles/GlobalLayout.css`  
**Taille:** ~700 lignes  
**Dépendances:** Aucune (CSS pur)

**Sections:**
```css
/* Variables CSS */
:root { --accent-color, --gradient-color, ... }

/* Main Layout Container */
.app-layout { ... }
.app-content { ... }
.main-content { ...}

/* Sidebar */
.sidebar { ... }
.sidebar header { ... }
.sidebar a { ... }
.sidebar a:hover { ... }

/* Animations */
@keyframes float-blob-1 { ... }
@keyframes float-blob-2 { ... }

/* Responsive */
@media (max-width: 860px) { ... }

/* Scrollbar */
::-webkit-scrollbar { ... }

/* Glassmorphism */
.glass-effect { ... }
```

**À modifier pour customizer:**
1. Couleurs: Variables `:root`
2. Sidebar width: `.sidebar { width: 240px }`
3. Animations: `@keyframes` definitions
4. Breakpoints: `@media` queries

---

### 2. **Layout.tsx** — Composant Principal
**Localisation:** `src/components/Layout.tsx`  
**Taille:** ~80 lignes  
**Dépendances:** React, React Router, GlobalLayout.css

**Structure:**
```tsx
export const Layout: React.FC<LayoutProps> = ({ children }) => {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const location = useLocation()
  
  const menuItems = [...]  // Navigation items
  const isActive = (path: string) => {...}  // Active state
  
  return (
    <div className="app-layout">
      {/* Blobs animés */}
      {/* Toggle checkbox */}
      {/* Sidebar nav */}
      {/* Main content */}
    </div>
  )
}
```

**À modifier pour ajouter/retirer des pages:**
```tsx
const menuItems = [
  { path: '/', label: 'Dashboard', icon: '📊' },
  // Ajouter/retirer ici
]
```

---

### 3. **App.tsx** — Configuration Routing
**Localisation:** `src/App.tsx`  
**Modification clé:** Ligne 10
```tsx
// AVANT:
import { MainLayout } from './layouts/MainLayout'

// APRÈS:
import { Layout } from './components/Layout'

// AVANT:
<MainLayout>
  <Routes>...</Routes>
</MainLayout>

// APRÈS:
<Layout>
  <Routes>...</Routes>
</Layout>
```

---

### 4. **main.tsx** — Entry Point
**Localisation:** `src/main.tsx`  
**Ligne importante:** 5
```tsx
import './styles/GlobalLayout.css'  // ← Charge les styles globaux
```

**Sans cette ligne:** Le design ne s'applique pas !

---

## 🎨 Customization Guide

### Changer les Couleurs

**Fichier:** `src/styles/GlobalLayout.css`  
**Localisation:** Lines 8-14

```css
:root {
  --accent-color: #fff;  /* ← Hover color */
  --gradient-color: #FBFBFB;  /* ← Gradient color */
  --primary-purple: #a759f5;  /* ← Main brand */
  --secondary-purple: #d6adff;  /* ← Lighter shade */
  --light-purple: #e8d1ff;  /* ← Background */
  --text-dark: #353535;  /* ← Text color */
}
```

**Exemple - Convertir en vert:**
```css
:root {
  --accent-color: #22c55e;
  --gradient-color: #dcfce7;
  --primary-purple: #059669;
  --secondary-purple: #6ee7b7;
  --light-purple: #d1fae5;
  --text-dark: #1f2937;
}
```

### Changer le Background Gradient

**Fichier:** `src/styles/GlobalLayout.css`  
**Localisation:** Line 26

```css
body {
  background-image: linear-gradient(-45deg, #e3eefe 0%, #efddfb 100%);
  /* ↓ Remplacer par votre gradient ↓ */
  background-image: linear-gradient(-45deg, #your-color-1 0%, #your-color-2 100%);
}
```

**Exemples:**
```css
/* Bleu océan */
background-image: linear-gradient(-45deg, #1e3a8a 0%, #0369a1 100%);

/* Rose flamant */
background-image: linear-gradient(-45deg, #be185d 0%, #f43f5e 100%);

/* Forêt */
background-image: linear-gradient(-45deg, #166534 0%, #15803d 100%);
```

### Changer la Largeur Sidebar

**Fichier:** `src/styles/GlobalLayout.css`  
**Localisation:** Line 93

```css
.sidebar {
  width: 240px;  /* ← Changer ici */
  left: -240px;  /* ← Doit correspondre (-width) */
}

#check:checked ~ label #btn {
  margin-left: 245px;  /* ← Doit être width + 5 */
}

#check:checked ~ label #cancel {
  margin-left: 245px;  /* ← Idem */
}
```

**Exemple - Sidebar 300px:**
```css
.sidebar { width: 300px; left: -300px; }
#check:checked ~ label #btn { margin-left: 305px; }
#check:checked ~ label #cancel { margin-left: 305px; }
```

### Ajouter une Nouvelle Page au Menu

**Fichier:** `src/components/Layout.tsx`  
**Localisation:** Lines 18-28

```tsx
const menuItems = [
  { path: '/', label: 'Dashboard', icon: '📊' },
  { path: '/cameras', label: 'Cameras', icon: '📷' },
  // ↓ Ajouter ici:
  { path: '/new-page', label: 'New Page', icon: '🆕' },
  // ↑
  { path: '/settings', label: 'Settings', icon: '⚙️' },
]
```

Puis créer la page dans `src/pages/NewPage.tsx` et l'importer dans `App.tsx`

### Changer les Animations

**Modifier le Float Blob:**

```css
@keyframes float-blob-1 {
  0%, 100% { transform: translate(0, 0); }
  33% { transform: translate(30px, -30px); }
  66% { transform: translate(-30px, 30px); }
}

.blob-1 {
  animation: float-blob-1 20s infinite ease-in-out;  /* ← 20s, ease-in-out */
}
```

**Rendre plus rapide (5s au lieu de 20s):**
```css
.blob-1 {
  animation: float-blob-1 5s infinite ease-in-out;
}
```

---

## 🔧 Common Issues & Solutions

### Sidebar ne s'ouvre pas
**Cause:** GlobalLayout.css non chargé  
**Solution:** Vérifier line 5 de `main.tsx`
```tsx
import './styles/GlobalLayout.css'  // Doit être présent
```

### Couleurs ne changent pas
**Cause:** Variables CSS pas mis à jour  
**Solution:** Vérifier `:root` en haut de GlobalLayout.css

### Background blur ne fonctionne pas
**Cause:** Navigateur ancien ou `backdrop-filter` désactivé  
**Solution:** 
- Firefox: `layout.css.backdrop-filter.enabled = true`
- Chrome: Généralement supporté
- Safari: Généralement supporté
- IE11: Non supporté

### Sidebar décalé sur mobile
**Cause:** Media query breakpoint mal configuré  
**Solution:** Vérifier `@media (max-width: 860px)` line 380+

---

## 📝 Pattern & Best Practices

### Ajouter une Nouvelle Animation

**Dans GlobalLayout.css:**
```css
@keyframes myNewAnimation {
  0% { opacity: 0; transform: translateY(-20px); }
  50% { opacity: 0.5; }
  100% { opacity: 1; transform: translateY(0); }
}

.my-element {
  animation: myNewAnimation 0.5s ease-in-out;
}
```

### Ajouter un Hover Effect Glassmorphism

```css
.my-card {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  transition: all 0.3s ease;
}

.my-card:hover {
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(15px);
  border: 1px solid rgba(255, 255, 255, 0.2);
}
```

### Ajouter un Responsive Grid

```tsx
<div style={{
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
  gap: '16px',
}}>
  {items.map(item => (...))}
</div>
```

---

## 🚀 Déploiement & Build

### Development
```bash
cd vms/frontend
npm run dev
# → http://localhost:3000
```

### Production Build
```bash
cd vms/frontend
npm run build
# → Output: dist/
```

### Vérifier Erreurs Build
```bash
npm run preview  # Preview production build locally
```

---

## 📊 Performance Tips

### Optimiser les Animations
- ✓ Utiliser GPU-accelerated properties (`transform`, `opacity`)
- ✓ Éviter `left`, `top` (triggerrez reflow)
- ✗ Éviter les ombres dinamiques
- ✗ Éviter les animations en JavaScript

### Réduire Bundle Size
- ✓ Code-split les routes
- ✓ Lazy-load les composants
- ✓ Tree-shake les imports
- ✓ Minify CSS/JS

### Améliorer Core Web Vitals
- ✓ First Paint < 1s
- ✓ Largest Contentful Paint < 2.5s
- ✓ Cumulative Layout Shift < 0.1

---

## 🔗 Références & Ressources

**MDN Documentation:**
- [CSS backdrop-filter](https://developer.mozilla.org/en-US/docs/Web/CSS/backdrop-filter)
- [CSS animations](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_Animations)
- [CSS Grid](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_Grid_Layout)

**React-Router v6:**
- [Official Docs](https://reactrouter.com/docs/)
- [useLocation Hook](https://reactrouter.com/docs/en/v6/hooks/use-location)

**Vite:**
- [Official Docs](https://vitejs.dev/)
- [Configuration](https://vitejs.dev/config/)

---

## 📞 Support & Issues

**Si vous rencontrez un problème:**

1. Vérifier browser console (F12)
2. Vérifier les CSS variables
3. Vérifier les imports
4. Clear cache & rebuild
5. Check GitHub issues

**Fichiers pour déboguer:**
- `src/styles/GlobalLayout.css` - CSS system
- `src/components/Layout.tsx` - Layout logic
- `src/App.tsx` - Routing config
- `vms/frontend/vite.config.ts` - Build config

---

**Last Updated:** 16 February 2026  
**Version:** 1.0.0  
**Status:** Production Ready ✓
