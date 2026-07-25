import pytest
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.db import transaction
from django.utils import timezone
from unittest.mock import patch

from app.models import (
    BeerUser, UserFollow, Brewery, Beer, Drinks, BeerSpot, 
    Report, UserBlock, Notification, UserAchievementState, 
    DrinkReaction, CustomNotebook
)

pytestmark = pytest.mark.django_db

# ==========================================
# FIXTURES (DRY Principle)
# ==========================================

@pytest.fixture
def base_user():
    return BeerUser.objects.create(username="tester", email="test@test.com")

@pytest.fixture
def target_user():
    return BeerUser.objects.create(username="target", email="target@test.com")

@pytest.fixture
def base_brewery():
    return Brewery.objects.create(name="Brasserie Test", description="Desc", city="Paris")

@pytest.fixture
def base_beer(base_brewery):
    # On mock le service d'embedding pour ne pas appeler l'API Gemini pendant la création de fixture
    with patch('app.services.get_embedding', return_value=[0.1] * 3072):
        return Beer.objects.create(
            name="Test Beer", 
            description="Test Desc", 
            brewery_id=base_brewery,
            degree=5.5
        )

@pytest.fixture
def base_drink(base_user, base_beer):
    return Drinks.objects.create(
        drinker_id=base_user, 
        beer_id=base_beer, 
        note=8, 
        comment="Excellent"
    )

# ==========================================
# TESTS : BeerUser
# ==========================================

def test_beeruser_str_and_properties(base_user):
    """Vérifie la représentation string et la propriété de notification[cite: 11]."""
    assert str(base_user) == "tester"
    assert base_user.has_unread_notifications is False

    Notification.objects.create(recipient=base_user, notif_type='follow')
    assert base_user.has_unread_notifications is True

def test_beeruser_unique_constraints():
    """Tente une attaque par duplication de données (Username / Email)[cite: 11]."""
    BeerUser.objects.create(username="unique_user", email="1@test.com")
    
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            BeerUser.objects.create(username="unique_user", email="2@test.com")
            
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            BeerUser.objects.create(username="another_user", email="1@test.com")

# ==========================================
# TESTS : Beer (Logique métier complexe)
# ==========================================

@patch('app.services.get_embedding')
def test_beer_save_slug_generation(mock_get_embedding, base_brewery):
    """Vérifie la génération automatique du slug et l'évitement des doublons[cite: 11]."""
    mock_get_embedding.return_value = [0.1] * 3072
    
    beer1 = Beer.objects.create(name="Super IPA", description="Test", brewery_id=base_brewery)
    assert beer1.slug == "super-ipa"
    
    # Création d'une bière avec exactement le même nom (doit générer un slug -1)
    # Note: name est UNIQUE, donc on doit tester la logique du slug avec un nom différent
    # mais qui générerait le même base_slug (ex: "super ipa" vs "Super IPA")
    beer2 = Beer.objects.create(name="Super IPA!", description="Test", brewery_id=base_brewery)
    beer2.save()
    
    assert beer2.slug == "super-ipa-1"
    
def test_beer_string_limits(base_brewery):
    """Tente une attaque de type Buffer Overflow (dépassement de la longueur max)[cite: 11]."""
    long_name = "A" * 151
    beer = Beer(name=long_name, description="Test", brewery_id=base_brewery)
    
    with pytest.raises(ValidationError):
        beer.full_clean()

# ==========================================
# TESTS : Drinks (Validateurs)
# ==========================================

def test_drinks_note_validators(base_user, base_beer):
    """Vérifie les contraintes strictes sur la notation (0 à 10)[cite: 11]."""
    # Valeur négative
    drink_under = Drinks(drinker_id=base_user, beer_id=base_beer, note=-1)
    with pytest.raises(ValidationError):
        drink_under.full_clean()
        
    # Valeur au-dessus de la limite
    drink_over = Drinks(drinker_id=base_user, beer_id=base_beer, note=11)
    with pytest.raises(ValidationError):
        drink_over.full_clean()
        
    # Injection de code / XSS dans le commentaire
    drink_xss = Drinks(drinker_id=base_user, beer_id=base_beer, note=5, comment="<script>alert(1)</script>")
    drink_xss.full_clean() # La base accepte le texte, la protection XSS doit se faire dans le template Django
    assert "<script>" in drink_xss.comment

def test_drinks_str(base_drink):
    assert str(base_drink) == "tester - Test Beer (8/10)"

# ==========================================
# TESTS : Notification (Propriété calculée)
# ==========================================

def test_notification_time_ago(base_user):
    """Teste toutes les conditions de la méthode time_ago avec manipulation du temps[cite: 11]."""
    notif = Notification.objects.create(recipient=base_user, notif_type='follow')
    
    # Simulation: À l'instant
    assert notif.time_ago == "à l'instant"
    
    # Simulation: Minutes
    notif.created_at = timezone.now() - timedelta(minutes=15)
    notif.save()
    assert notif.time_ago == "15 min"
    
    # Simulation: Heures
    notif.created_at = timezone.now() - timedelta(hours=3, minutes=15)
    notif.save()
    assert notif.time_ago == "3h"
    
    # Simulation: Jours
    notif.created_at = timezone.now() - timedelta(days=2, hours=1)
    notif.save()
    assert notif.time_ago == "2 j"

# ==========================================
# TESTS : Contraintes UNIQUE_TOGETHER
# ==========================================

def test_unique_together_constraints(base_user, target_user, base_drink):
    """Prouve que la base de données bloque strictement les duplications métier[cite: 11]."""
    
    # 1. UserFollow
    UserFollow.objects.create(follower=base_user, followed=target_user)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            UserFollow.objects.create(follower=base_user, followed=target_user)
            
    # 2. UserBlock
    UserBlock.objects.create(blocker=base_user, blocked=target_user)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            UserBlock.objects.create(blocker=base_user, blocked=target_user)
            
    # 3. UserAchievementState
    UserAchievementState.objects.create(user=base_user, achievement_name="Poche")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            UserAchievementState.objects.create(user=base_user, achievement_name="Poche")
            
    # 4. DrinkReaction
    DrinkReaction.objects.create(user=base_user, drink=base_drink, is_like=True)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DrinkReaction.objects.create(user=base_user, drink=base_drink, is_like=False)

# ==========================================
# TESTS : Méthodes __str__ restantes
# ==========================================

def test_remaining_str_methods(base_user, target_user, base_brewery, base_drink):
    """Valide les représentations textuelles pour l'Admin Django et les logs[cite: 11]."""
    assert str(base_brewery) == "Brasserie Test"
    
    spot = BeerSpot.objects.create(user=base_user, title="Mon Bar", latitude=48.0, longitude=2.0)
    assert str(spot) == "Mon Bar - tester"
    
    report = Report.objects.create(reporter=base_user, reported_user=target_user, reason='spam')
    assert str(report) == f"Signalement #{report.id} par tester - Envoyé"
    
    block = UserBlock.objects.filter(blocker=base_user).first()
    if not block:
        block = UserBlock.objects.create(blocker=base_user, blocked=target_user)
    assert str(block) == "tester a bloqué target"
    
    notebook = CustomNotebook.objects.create(user=base_user, title="Top IPA")
    assert str(notebook) == "Top IPA - tester"