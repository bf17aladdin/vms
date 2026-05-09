#!/usr/bin/env python3
"""
Test complet de l'implémentation des standards militaires
pour Personnel et Véhicules

Tests complètement E2E:
1. API Personnel militaire (CRUD + filtres + actions)
2. API Registre Véhicules (CRUD + flag/unflag + stats)
3. Intégration base de données
4. Validation des schémas Pydantic
"""

import requests
import json
import sys
from pathlib import Path

# Constants
API_BASE = "http://localhost:8000/api"
ADMIN_USER = "admin"
ADMIN_PASS = "admin123"

class TestColors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    END = "\033[0m"

def log_test(name: str, passed: bool, message: str = ""):
    status = f"{TestColors.GREEN}✓ PASS{TestColors.END}" if passed else f"{TestColors.RED}✗ FAIL{TestColors.END}"
    print(f"{status} {name}")
    if message:
        print(f"  → {message}")

def log_section(title: str):
    print(f"\n{TestColors.BLUE}{'='*60}")
    print(f"{title}")
    print(f"{'='*60}{TestColors.END}\n")

class MilitaryStandardsTest:
    def __init__(self):
        self.token = None
        self.personnel_ids = []
        self.vehicle_ids = []
        self.session = requests.Session()

    def authenticate(self):
        """Test 1: Authentification"""
        log_section("1. AUTHENTIFICATION")
        
        try:
            resp = self.session.post(
                f"{API_BASE}/auth/login",
                json={"username": ADMIN_USER, "password": ADMIN_PASS}
            )
            if resp.status_code == 200:
                self.token = resp.json().get('access_token')
                self.session.headers.update({'Authorization': f'Bearer {self.token}'})
                log_test("Login réussi", True, f"Token obtenu")
                return True
            else:
                log_test("Login réussi", False, f"Status: {resp.status_code}")
                return False
        except Exception as e:
            log_test("Connexion API", False, str(e))
            return False

    # ===== PERSONNEL TESTS =====
    
    def test_personnel_create(self):
        """Test 2: Création personnel"""
        log_section("2. PERSONNEL - CRÉATION")
        
        test_data = {
            "nom": "Dupont",
            "prenom": "Jean",
            "cin": "ST12345678901",
            "num_recrutement": "REC2024001",
            "grade": "Capitaine",
            "categorie": "officier",
            "unité": "1er Régiment",
            "email": "jean.dupont@army.test",
            "telephone": "+33612345678"
        }
        
        try:
            resp = self.session.post(
                f"{API_BASE}/personnel",
                json=test_data
            )
            if resp.status_code == 201:
                data = resp.json()
                person_id = data.get('id')
                self.personnel_ids.append(person_id)
                log_test("Création personnel", True, f"ID: {person_id}")
                return person_id
            else:
                log_test("Création personnel", False, f"Status: {resp.status_code}")
                return None
        except Exception as e:
            log_test("Création personnel", False, str(e))
            return None

    def test_personnel_get(self, person_id):
        """Test 3: Récupération personnel"""
        try:
            resp = self.session.get(f"{API_BASE}/personnel/{person_id}")
            if resp.status_code == 200:
                data = resp.json()
                log_test("Récupération personnel", True, f"{data.get('nom')} {data.get('prenom')}")
                return data
            else:
                log_test("Récupération personnel", False, f"Status: {resp.status_code}")
                return None
        except Exception as e:
            log_test("Récupération personnel", False, str(e))
            return None

    def test_personnel_filters(self):
        """Test 4: Filtres avancés"""
        log_section("3. PERSONNEL - FILTRES")
        
        filters = [
            ("categorie=officier", "Filtre par catégorie (Officier)"),
            ("grade=Capitaine", "Filtre par grade (Capitaine)"),
            ("is_active=true", "Filtre actifs uniquement"),
        ]
        
        for filter_str, desc in filters:
            try:
                resp = self.session.get(f"{API_BASE}/personnel?{filter_str}")
                if resp.status_code == 200:
                    count = len(resp.json())
                    log_test(desc, True, f"{count} résultats")
                else:
                    log_test(desc, False, f"Status: {resp.status_code}")
            except Exception as e:
                log_test(desc, False, str(e))

    def test_personnel_blacklist(self, person_id):
        """Test 5: Signalement personnel"""
        try:
            resp = self.session.post(
                f"{API_BASE}/personnel/{person_id}/blacklist?reason=Test+signalement",
                json={}
            )
            if resp.status_code == 200:
                log_test("Signalement personnel", True, "Ajout à la liste noire")
                return True
            else:
                log_test("Signalement personnel", False, f"Status: {resp.status_code}")
                return False
        except Exception as e:
            log_test("Signalement personnel", False, str(e))
            return False

    def test_personnel_stats(self):
        """Test 6: Stats personnel"""
        try:
            resp = self.session.get(f"{API_BASE}/personnel/stats/summary")
            if resp.status_code == 200:
                stats = resp.json()
                log_test("Stats personnel", True, 
                    f"Total: {stats.get('total')}, "
                    f"Actifs: {stats.get('actifs')}, "
                    f"Signalés: {stats.get('blacklistes')}")
                return stats
            else:
                log_test("Stats personnel", False, f"Status: {resp.status_code}")
                return None
        except Exception as e:
            log_test("Stats personnel", False, str(e))
            return None

    # ===== VEHICLE REGISTRY TESTS =====

    def test_vehicle_create(self):
        """Test 7: Création véhicule"""
        log_section("4. REGISTRE VÉHICULES - CRÉATION")
        
        test_data = {
            "immatriculation": "MA123456",
            "marque_modele": "Toyota Land Cruiser",
            "numero_serie": "LFVVR6H79FP123456",
            "couleur": "Vert militaire",
            "type_vehicule": "militaire",
            "proprietaire": "Ministère Défense",
            "nom_conducteur": "Dupont Jean",
            "etat": "actif"
        }
        
        try:
            resp = self.session.post(
                f"{API_BASE}/vehicle-registry/create",
                json=test_data
            )
            if resp.status_code == 201:
                data = resp.json()
                vehicle_id = data.get('id')
                self.vehicle_ids.append(vehicle_id)
                log_test("Création véhicule", True, f"ID: {vehicle_id}")
                return vehicle_id
            else:
                log_test("Création véhicule", False, f"Status: {resp.status_code}")
                return None
        except Exception as e:
            log_test("Création véhicule", False, str(e))
            return None

    def test_vehicle_list(self):
        """Test 8: Liste véhicules"""
        try:
            resp = self.session.get(f"{API_BASE}/vehicle-registry/list")
            if resp.status_code == 200:
                vehicles = resp.json()
                count = len(vehicles) if isinstance(vehicles, list) else 1
                log_test("Liste véhicules", True, f"{count} véhicules trouvés")
                return vehicles
            else:
                log_test("Liste véhicules", False, f"Status: {resp.status_code}")
                return None
        except Exception as e:
            log_test("Liste véhicules", False, str(e))
            return None

    def test_vehicle_filters(self):
        """Test 9: Filtres véhicules"""
        log_section("5. REGISTRE VÉHICULES - FILTRES")
        
        filters = [
            ("type_vehicule=militaire", "Filtre par type (Militaire)"),
            ("etat=actif", "Filtre par état (Actif)"),
            ("is_flagged=false", "Filtre non signalés"),
        ]
        
        for filter_str, desc in filters:
            try:
                resp = self.session.get(f"{API_BASE}/vehicle-registry/list?{filter_str}")
                if resp.status_code == 200:
                    count = len(resp.json()) if isinstance(resp.json(), list) else 1
                    log_test(desc, True, f"{count} résultats")
                else:
                    log_test(desc, False, f"Status: {resp.status_code}")
            except Exception as e:
                log_test(desc, False, str(e))

    def test_vehicle_flag(self, vehicle_id):
        """Test 10: Signalement véhicule"""
        try:
            resp = self.session.post(
                f"{API_BASE}/vehicle-registry/{vehicle_id}/flag",
                json={"reason": "Véhicule suspect"}
            )
            if resp.status_code == 200:
                log_test("Signalement véhicule", True, "Marqué comme signalé")
                return True
            else:
                log_test("Signalement véhicule", False, f"Status: {resp.status_code}")
                return False
        except Exception as e:
            log_test("Signalement véhicule", False, str(e))
            return False

    def test_vehicle_stats(self):
        """Test 11: Stats véhicules"""
        try:
            resp = self.session.get(f"{API_BASE}/vehicle-registry/stats/summary")
            if resp.status_code == 200:
                stats = resp.json()
                log_test("Stats véhicules", True, 
                    f"Total: {stats.get('total')}, "
                    f"Signalés: {stats.get('signales')}")
                return stats
            else:
                log_test("Stats véhicules", False, f"Status: {resp.status_code}")
                return None
        except Exception as e:
            log_test("Stats véhicules", False, str(e))
            return None

    # ===== CLEANUP =====

    def cleanup(self):
        """Nettoyage des ressources de test"""
        log_section("6. NETTOYAGE")
        
        for person_id in self.personnel_ids:
            try:
                self.session.delete(f"{API_BASE}/personnel/{person_id}")
            except:
                pass
        
        for vehicle_id in self.vehicle_ids:
            try:
                self.session.delete(f"{API_BASE}/vehicle-registry/{vehicle_id}")
            except:
                pass

    def run(self):
        """Exécuter tous les tests"""
        print(f"\n{TestColors.BLUE}")
        print("="*60)
        print("TEST COMPLET - STANDARDS MILITAIRES")
        print("="*60)
        print(f"{TestColors.END}\n")
        
        # Authentification
        if not self.authenticate():
            print(f"\n{TestColors.RED}✗ Authentification échouée{TestColors.END}")
            return False

        # Tests Personnel
        person_id = self.test_personnel_create()
        if person_id:
            self.test_personnel_get(person_id)
            self.test_personnel_filters()
            self.test_personnel_blacklist(person_id)
        
        self.test_personnel_stats()

        # Tests Véhicules
        vehicle_id = self.test_vehicle_create()
        if vehicle_id:
            self.test_vehicle_list()
            self.test_vehicle_filters()
            self.test_vehicle_flag(vehicle_id)
        
        self.test_vehicle_stats()

        # Cleanup
        self.cleanup()

        print(f"\n{TestColors.BLUE}{'='*60}")
        print("TEST COMPLET TERMINÉ")
        print(f"{'='*60}{TestColors.END}\n")
        
        return True

if __name__ == "__main__":
    try:
        tester = MilitaryStandardsTest()
        tester.run()
    except KeyboardInterrupt:
        print(f"\n{TestColors.YELLOW}Test interrompu{TestColors.END}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{TestColors.RED}Erreur: {str(e)}{TestColors.END}")
        sys.exit(1)
