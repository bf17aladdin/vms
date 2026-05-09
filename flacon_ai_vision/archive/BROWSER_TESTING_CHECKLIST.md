# ✅ VMS Browser Testing Checklist

Complete this checklist to verify all functionality works correctly.

---

## 🔐 Authentication & Navigation

- [ ] **Login Page Displays**
  - [ ] Load http://localhost:5003
  - [ ] See login form with username/password fields
  - [ ] See Falcon AI Vision logo/branding

- [ ] **Login Works**
  - [ ] Enter `admin` / `admin123`
  - [ ] Click Login
  - [ ] Redirected to Dashboard
  - [ ] localStorage contains JWT token (DevTools → Application → localStorage)

- [ ] **Navigation Sidebar**
  - [ ] Sidebar displays 12 main menu items
  - [ ] Icons visible next to each item
  - [ ] Sidebar collapses/expands (toggle icon)
  - [ ] Settings menu at bottom
  - [ ] Logout button works

- [ ] **Role-based Access (Optional)**
  - [ ] Create test user with role "user"
  - [ ] Login as test user
  - [ ] Cannot see admin-only pages (Users, Scenarios, etc.)
  - [ ] Can see regular pages (Camera, Alerts, etc.)

---

## 📊 Dashboard

- [ ] **Page Loads**
  - [ ] Dashboard displays without errors
  - [ ] See 5 stat cards (Cameras, Events, Zones, Personnel, Vehicles)
  - [ ] Recent Events section visible

- [ ] **Real-time Updates**
  - [ ] 🟢 Live badge showing (green)
  - [ ] "Last update" timestamp visible
  - [ ] (Optional: Trigger backend event, stats update without refresh)

- [ ] **Stat Cards Display**
  - [ ] Active Cameras: Shows X/Y format
  - [ ] Unacknowledged Events: Shows count in red
  - [ ] Zones: Shows total count
  - [ ] Personnel: Shows count
  - [ ] Vehicles: Shows count

- [ ] **Recent Events List**
  - [ ] Shows last 5 events
  - [ ] Each event has: Type badge, Severity, Camera#, Timestamp
  - [ ] NEW badge on live events
  - [ ] Pulse animation on new events

---

## 📹 Cameras Page

- [ ] **Page Loads**
  - [ ] Camera list displays
  - [ ] See table with columns: Name, Type, Status, Resolution, etc.

- [ ] **Functional Actions**
  - [ ] Click "Details" on any camera → Modal opens
  - [ ] Modal shows all camera info
  - [ ] Click "Edit" → Can modify camera name/description
  - [ ] Click "Test Connection" → Gets response (online/offline)
  - [ ] Click "Delete" → Confirms then removes camera
  - [ ] Click "Close" → Modal closes

- [ ] **Search & Filter**
  - [ ] Type in search field → Table filters by camera name
  - [ ] Clear search → Full list returns

- [ ] **Loading States**
  - [ ] See spinner while loading
  - [ ] Disable buttons while saving
  - [ ] Show error messages on failure

---

## 🔴 Alerts Page  ⭐ REAL-TIME

- [ ] **Page Loads**
  - [ ] Alert list displays
  - [ ] See table with: Name, Type, Severity, Status, Camera#, Triggered

- [ ] **Real-time Updates** (WebSocket)
  - [ ] 🟢 Live badge showing
  - [ ] "Last update" timestamp
  - [ ] (Optional: Trigger alert from backend, appears instantly without refresh)

- [ ] **Filtering Works**
  - [ ] Severity buttons (all, low, medium, high, critical) work
  - [ ] Search box filters by name/description
  - [ ] Both filters combined work together

- [ ] **Actions Work**
  - [ ] Click "Acknowledge" → Alert updates
  - [ ] Click "Activate/Deactivate" → Status changes
  - [ ] Click "Delete" → Alert removed after confirmation

- [ ] **Severity Colors**
  - [ ] Critical: Red
  - [ ] High: Orange
  - [ ] Medium: Yellow
  - [ ] Low: Green

---

## 🤖 AI Monitoring Page  ⭐ REAL-TIME

- [ ] **Page Loads**
  - [ ] Detection grid displays
  - [ ] See detection cards with images/confidence

- [ ] **Real-time Updates** (WebSocket)
  - [ ] 🟢 Live badge showing
  - [ ] Detections appear without refresh
  - [ ] Counter updates for each type

- [ ] **Type Filters Work**
  - [ ] All button shows all detections
  - [ ] Face button shows only face detections (with count)
  - [ ] Person button shows only person detections
  - [ ] Vehicle button shows only vehicle detections
  - [ ] Object button shows only object detections

- [ ] **Detection Cards Display**
  - [ ] Type badge (Face, Person, Vehicle, Object)
  - [ ] Confidence percentage (top right)
  - [ ] Confidence bar (color: green if >90%, yellow if >75%, red if <75%)
  - [ ] Camera # and Zone
  - [ ] Detection timestamp
  - [ ] Detection image thumbnail

- [ ] **Cards are Responsive**
  - [ ] 1 column on mobile
  - [ ] 2 columns on tablet/desktop
  - [ ] Hover effect (shadow increases)

---

## 🗺️ Zones Page  ⭐ REAL-TIME

- [ ] **Page Loads**
  - [ ] Zone list displays in table
  - [ ] Columns: Name, Description, Occupancy, Status

- [ ] **Real-time Occupancy** (WebSocket)
  - [ ] 🟢 Live badge showing
  - [ ] Occupancy numbers update without refresh
  - [ ] Progress bars change color in real-time

- [ ] **Occupancy Progress Bars**
  - [ ] Green: 0-50%
  - [ ] Yellow: 50-80%
  - [ ] Red: >80%
  - [ ] Shows X/Y format (current/limit)

- [ ] **Details Modal**
  - [ ] Click "Details" → Modal opens
  - [ ] Shows zone name, description, status
  - [ ] Shows big occupancy progress bar
  - [ ] Shows "LIVE" indicator if receiving WebSocket updates
  - [ ] Occupancy updates in modal in real-time
  - [ ] Click "Close" → Modal closes

- [ ] **Search Works**
  - [ ] Type zone name → Table filters

---

## 👤 Personnel Page

- [ ] **Page Loads**
  - [ ] Personnel list displays
  - [ ] See table with: Name, Known Faces, Last Seen, Status

- [ ] **Functional**
  - [ ] Click "Register Face" → Form to add new person
  - [ ] Click "View History" → Shows recognition history
  - [ ] Can see person's registered face image

- [ ] **Search Works**
  - [ ] Type name → Table filters

---

## 🚗 Vehicles Page

- [ ] **Page Loads**
  - [ ] Vehicle list displays
  - [ ] See table with: License Plate, Make/Model, Status

- [ ] **Functional**
  - [ ] Click a vehicle → Details modal
  - [ ] Can see: License plate, color, Make/Model
  - [ ] Can see whitelist/blacklist status
  - [ ] Can add/remove from whitelist

---

## 📋 Events Page

- [ ] **Page Loads**
  - [ ] Event list displays  
  - [ ] See table with timestamp, type, severity, camera

- [ ] **Search/Filter Works**
  - [ ] Date range picker works
  - [ ] Event type filter works
  - [ ] Severity filter works

- [ ] **Export Works**
  - [ ] Click "Export" button
  - [ ] Can select format: PDF, CSV, XLSX
  - [ ] Download starts

---

## 📄 Reporting Page

- [ ] **Page Loads**
  - [ ] Report types visible: PDF, CSV, XLSX
  - [ ] Date range selector available

- [ ] **Generate Report**
  - [ ] Select report type
  - [ ] Select date range
  - [ ] Click "Generate"
  - [ ] File downloads

---

## ⚙️ Settings Page

- [ ] **User Profile**
  - [ ] Shows current user name
  - [ ] Shows email
  - [ ] Shows role (Admin/User)
  - [ ] Can edit full name

- [ ] **Change Password**
  - [ ] Can enter current password
  - [ ] Can enter new password
  - [ ] Validation: Password strength indicator
  - [ ] Submit works

- [ ] **System Info**
  - [ ] Shows database version
  - [ ] Shows backend version
  - [ ] Shows frontend version
  - [ ] Shows last backup date

---

## 🔌 WebSocket Verification

- [ ] **Open DevTools**
  - [ ] Press F12
  - [ ] Go to Network tab
  - [ ] Filter:  "WS" (WebSocket)

- [ ] **See WebSocket Connection**
  - [ ] See `/api/ws` entry
  - [ ] Status: 101 Switching Protocols ✓
  - [ ] Click it → See Frames tab
  - [ ] Messages flowing in (real-time data)

- [ ] **Message Types** (in Frames)
  - [ ] See `{"type":"event"...}` messages
  - [ ] See `{"type":"alert"...}` messages
  - [ ] See `{"type":"occupancy"...}` messages
  - [ ] Messages come automatically (no polling)

- [ ] **Connection Resilience**
  - [ ] Close DevTools (re-opens connection)
  - [ ] Toggle network offline → 🟢 Live becomes ⚪ Offline
  - [ ] Toggle network back online → Reconnects automatically

---

## 🎨 UI/UX Checks

- [ ] **Responsive Design**
  - [ ] Works on phone (320px width)
  - [ ] Works on tablet (768px width)
  - [ ] Works on desktop (1920px width)
  - [ ] Menu adapts to screen size

- [ ] **Color Scheme**
  - [ ] Professional blue/gray colors
  - [ ] Status colors: 🟢 green, 🟡 yellow, 🔴 red
  - [ ] Badges visible and readable

- [ ] **Fonts & Typography**
  - [ ] Titles are bold and readable
  - [ ] Body text is legible
  - [ ] Timestamps are formatted consistently

- [ ] **Loading & Error States**
  - [ ] Loading spinners visible
  - [ ] Error messages visible
  - [ ] Success messages visible
  - [ ] Disabled buttons look disabled

---

## ⚠️ Error Handling

- [ ] **Invalid Login**
  - [ ] Try wrong password → Shows error
  - [ ] Try non-existent user → Shows error

- [ ] **API Errors**
  - [ ] Try to delete protected camera → Shows "Cannot delete" error
  - [ ] Try offline operation → Shows connectivity message

- [ ] **WebSocket Disconnect**
  - [ ] Unplug network → ⚪ Offline badge
  - [ ] Plug back in → Auto-reconnects
  - [ ] No page crash

---

## 📈 Performance Checks

- [ ] **Page Load Time**
  - [ ] Dashboard loads in <2 seconds
  - [ ] No visible layout shift
  - [ ] Images load smoothly

- [ ] **Real-time Responsiveness**
  - [ ] WebSocket messages arrive <500ms after backend sends
  - [ ] UI updates smoothly
  - [ ] No flickering

- [ ] **Memory**
  - [ ] Leave app running 5 minutes
  - [ ] Open DevTools → Memory
  - [ ] No memory leak (usage stable)

---

## ✅ Final Checklist

- [ ] All main pages load without errors
- [ ] Authentication works correctly  
- [ ] Real-time updates work (at least 3 pages)
- [ ] WebSocket connection visible in DevTools
- [ ] Responsive design works on multiple screen sizes
- [ ] Error handling in place
- [ ] No console errors (DevTools → Console)
- [ ] No network failures (DevTools → Network)
- [ ] Performance acceptable

---

## 📝 Notes

**Passed**: _____ / _____ checks

**Issues Found**:
```
(List any bugs or issues found during testing)




```

**Browser**: _________________ (Chrome/Firefox/Safari/Edge)  
**OS**: _________________ (Windows/Mac/Linux)  
**Date**: _________________  
**Tester**: _________________

---

**Status**: ✅ Ready for deployment / 🚧 Needs fixes

