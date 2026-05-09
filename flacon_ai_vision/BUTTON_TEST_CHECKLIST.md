# 🧪 Guide de Test - Tous les Boutons Frontend

**Date:** 16 février 2026  
**Objectif:** Vérifier que **TOUS les boutons** fonctionnent correctement

---

## 🎯 Checklist Complète

### ✅ Navigation & Authentification

#### Login Page (`http://localhost:3000`)
- [ ] **Login Button** - Clique → Connexion
  - Input: admin / admin123
  - Expected: Redirect vers /dashboard
  - Color: Vert militaire gradient

#### Logout (Everywhere)
- [ ] **Logout Button** (Sidebar bottom, red)
  - Icon: 🚪
  - Color: Rouge (#e74c3c)
  - Click: Redirect vers /login
  - Action: Supprime token

---

### 📊 Dashboard (`http://localhost:3000/dashboard`)

#### Buttons à Tester
- [ ] **Stats Cards** - Cliquables (interact)
- [ ] **Refresh Button** - Recharge les données
- [ ] **Alert Acknowledge** - Marque alerte lue
- [ ] **Event View** - Affiche détails event

#### Layout Buttons
- [ ] **Hamburger/Toggle** (☰) - Mobile: ouvre sidebar
- [ ] **Close/Cancel** (✕) - Mobile: ferme sidebar

---

### 📷 Cameras Page (`http://localhost:3000/cameras`)

#### Action Buttons
- [ ] **Add Camera** - Ouvre modal
  - Form fields: Name, Location, IP, RTSP URL
  - Buttons dans modal:
    - [ ] **Create** - Crée camera
    - [ ] **Cancel** - Ferme modal

- [ ] **Camera 3D Buttons** - Clique caméra
  - Opens details modal
  - Buttons dans modal:
    - [ ] **Edit** - Modal édition
    - [ ] **Close** - Ferme modal

#### Data Table Actions
- [ ] **View** - Affiche détails
- [ ] **Edit** - Ouvre modal d'édition
  - Buttons dans modal:
    - [ ] **Update** - Sauvegarde
    - [ ] **Cancel** - Annule
- [ ] **Delete** - Supprime caméra

#### Form Buttons (Edit/Add)
- [ ] **Motion Detection** - Checkbox toggle
- [ ] **Object Detection** - Checkbox toggle
- [ ] **AI Enabled** - Checkbox toggle
- [ ] **Submit** - Sauvegarde

---

### 🔔 Alerts Page (`http://localhost:3000/alerts`)

#### Filter Buttons
- [ ] **All** - Affiche tous les alerts
- [ ] **Low** - Filtre severity low
- [ ] **Medium** - Filtre severity medium
- [ ] **High** - Filtre severity high
- [ ] **Critical** - Filtre severity critical

#### Search & Refresh
- [ ] **Search Input** - Filtre par texte
- [ ] **Refresh Button** - Recharge données

#### Data Table Actions
- [ ] **Acknowledge** - Marque alerte lue
- [ ] **Deactivate/Activate** - Toggle état
- [ ] **Delete** - Supprime alerte

---

### ⚡ Events Page (`http://localhost:3000/events`)

#### Top Actions
- [ ] **Search Input** - Filtre events
- [ ] **Refresh Button** - Recharge liste

#### Event Cards
- [ ] **Click Event Card** - Affiche détails
- [ ] **Event Details Modal**
  - Buttons:
    - [ ] **Close/Back** - Ferme modal

#### Data Table
- [ ] **Event Rows** - Clickable rows
- [ ] **Severity Badge** - Color-coded
- [ ] **Timestamp** - Readable format

---

### 🗺️ Zones Page (`http://localhost:3000/zones`)

#### Zone Management
- [ ] **Add Zone Button** - Ouvre modal
  - Modal form buttons:
    - [ ] **Create** - Crée zone
    - [ ] **Cancel** - Annule
- [ ] **Edit Zone** - Ouvre modal d'édition
  - Buttons:
    - [ ] **Update** - Sauvegarde
    - [ ] **Cancel** - Annule
- [ ] **Delete Zone** - Supprime
- [ ] **View Zone** - Affiche détails

---

### 👥 Personnel Page (`http://localhost:3000/personnel`)

#### Personnel Management
- [ ] **Add Personnel** - Ouvre modal
  - Buttons:
    - [ ] **Create** - Crée personnel
    - [ ] **Cancel** - Annule
- [ ] **Edit Personnel** - Modal édition
  - Buttons:
    - [ ] **Update** - Sauvegarde
    - [ ] **Cancel** - Annule
- [ ] **Delete** - Supprime
- [ ] **View Details** - Modal détails

#### Facial Recognition
- [ ] **Upload Photo** - Input file
- [ ] **Recognize** - Lance détection
- [ ] **Match Result** - Affiche résultat

---

### 🚗 Vehicles Page (`http://localhost:3000/vehicles`)

#### Vehicle Registry
- [ ] **Add Vehicle** - Modal creation
  - Buttons:
    - [ ] **Register** - Crée vehicle
    - [ ] **Cancel** - Annule
- [ ] **Edit Vehicle** - Modal édition
  - Buttons:
    - [ ] **Update** - Sauvegarde
    - [ ] **Cancel** - Annule
- [ ] **Delete** - Supprime
- [ ] **View** - Affiche détails

#### License Plate Search
- [ ] **Search Input** - Cherche plaque
- [ ] **Search Button** - Lance recherche
- [ ] **Results** - Affiche véhicules

---

### 📈 Reports Page (`http://localhost:3000/reporting`)

#### Report Generation
- [ ] **Date Picker Start** - Sélectionne date début
- [ ] **Date Picker End** - Sélectionne date fin
- [ ] **Generate Report** - Crée report
- [ ] **Export PDF** - Télécharge PDF
- [ ] **Export Excel** - Télécharge Excel

#### Report Filters
- [ ] **Filter by Type** - Events, Alerts, Persons
- [ ] **Filter by Severity** - Low/Med/High
- [ ] **Apply Filters** - Recharge rapport

---

### ⚙️ Settings Page (`http://localhost:3000/settings`)

#### General Settings
- [ ] **System Name** - Edit input
- [ ] **Save Settings** - Sauvegarde
- [ ] **Cancel** - Annule

#### Security Settings
- [ ] **Change Password** - Modal
  - [ ] **Current Password** - Input
  - [ ] **New Password** - Input
  - [ ] **Confirm Password** - Input
  - [ ] **Update** - Sauvegarde
  - [ ] **Cancel** - Annule

#### Notification Settings
- [ ] **Email Notifications** - Toggle
- [ ] **Push Notifications** - Toggle
- [ ] **Alert Types** - Checkboxes
- [ ] **Save** - Sauvegarde

---

### 🎛️ Admin Panel (`http://localhost:3000/admin`)

#### User Management
- [ ] **Add User** - Modal
  - Buttons:
    - [ ] **Create** - Crée user
    - [ ] **Cancel** - Annule
- [ ] **Edit User** - Modal édition
- [ ] **Delete User** - Supprime

#### System Configuration
- [ ] **System Status** - Button info
- [ ] **Restart Services** - Confirmation
- [ ] **Clear Cache** - Confirmation
- [ ] **Database Backup** - Action

---

### 🗺️ Map View (`http://localhost:3000/map`)

#### Map Controls
- [ ] **Zoom In** - Plus button
- [ ] **Zoom Out** - Minus button
- [ ] **Reset View** - Center button
- [ ] **Layer Toggle** - Show/hide layers
- [ ] **Camera Markers** - Clique camera

#### Sidebar Toggle (Mobile)
- [ ] **Hamburger** - Ouvre sidebar
- [ ] **Close** - Ferme sidebar

---

### 👁️ AI Monitoring (`http://localhost:3000/ai-monitoring`)

#### Detection Controls
- [ ] **Start Detection** - Lance détection
- [ ] **Stop Detection** - Arrête détection
- [ ] **Sensitivity Slider** - Ajuste sensibilité
- [ ] **Model Select** - Choix modèle IA

#### Detection Results
- [ ] **Clear History** - Vide historique
- [ ] **Export Results** - Télécharge données
- [ ] **View Details** - Affiche détail

---

## 🎨 Style & Layout Verification

### Colors
- [ ] Login page: Vert militaire gradient
- [ ] Sidebar: Vert primaire + accents
- [ ] Logout button: Rouge (#e74c3c)
- [ ] Hover states: Gradient vert
- [ ] All components: Consistent theming

### Responsive
- [ ] **Desktop (≥860px)**
  - Sidebar 240px visible
  - Full layout
  - All buttons accessible

- [ ] **Tablet (600-860px)**
  - Sidebar 70px icons
  - Responsive grid
  - Touch-friendly

- [ ] **Mobile (<600px)**
  - Hamburger menu active
  - One column layout
  - Buttons full width

### Animations
- [ ] Sidebar toggle: Smooth 0.5s
- [ ] Hover effects: Gradient changes
- [ ] Modal transitions: Fade in/out
- [ ] Loading states: Spinner visible
- [ ] No janky animations

---

## 📋 Test Result Summary

### Status Categories
- ✅ Fully Working
- ⚠️ Partially Working
- ❌ Not Working
- ⏭️ Skipped (Not Available)

### Quick Result Template
```
Total Buttons Tested: ___ / ___
✅ Fully Working: ___
⚠️  Partially Working: ___
❌ Not Working: ___

Critical Issues: None / [List]
Nice-to-Have Issues: [List]
```

---

## 🐛 Issue Reporting

If a button doesn't work:

1. **Check Console** (F12)
   - Any error messages?
   - Network requests failing?

2. **Check Backend**
   - API endpoint responding?
   - Database connected?

3. **Document Issue**
   - Button name
   - Page URL
   - Expected vs actual behavior
   - Error message (if any)

---

## ✨ Nice-to-Have Features

- [ ] Button tooltips on hover
- [ ] Loading states for all buttons
- [ ] Keyboard shortcuts (Enter, Escape)
- [ ] Aria labels for accessibility
- [ ] Confirmation dialogs for delete
- [ ] Toast notifications for feedback

---

**Last Updated:** 16 février 2026  
**Status:** Ready for Testing
