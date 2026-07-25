import pytest
from django.urls import reverse

@pytest.mark.django_db
def test_unauthenticated_user_cannot_access_account(client):
    """Vérifie qu'un visiteur non connecté est redirigé vers la page login."""
    url = reverse('account')
    response = client.get(url)
    
    assert response.status_code == 302
    assert response.url.startswith(reverse('login'))