from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import ProfilePictureForm
from ..models import BeerUser
from ..services.profile_pictures import COOLDOWN_SECONDS, delete_stored_picture


def _reserve_upload_slot(user):
    """Un envoi toutes les COOLDOWN_SECONDS par membre ; la réservation est atomique (deux requêtes simultanées : une seule passe)."""
    now = timezone.now()
    threshold = now - timedelta(seconds=COOLDOWN_SECONDS)
    return BeerUser.objects.filter(
        Q(avatar_updated_at__isnull=True) | Q(avatar_updated_at__lte=threshold), pk=user.pk,
    ).update(avatar_updated_at=now) == 1


@require_POST
@login_required(login_url='login')
def update_profile_picture(request):
    """Remplace la photo de profil du membre connecté (jamais celle d'un autre : aucun identifiant n'est accepté)."""
    user = request.user
    previous_update = user.avatar_updated_at
    if not _reserve_upload_slot(user):
        messages.error(request, "Patientez un instant avant de changer à nouveau votre photo.")
        return redirect('account')

    old_name = user.avatar.name if user.avatar else None
    form = ProfilePictureForm(request.POST, request.FILES, instance=user)
    if not form.is_valid():
        # Un fichier refusé ne doit pas bloquer le membre pendant le délai d'attente
        BeerUser.objects.filter(pk=user.pk).update(avatar_updated_at=previous_update)
        messages.error(request, " ".join(form.errors.get('avatar', ["Photo invalide."])))
        return redirect('account')

    form.save(commit=False)
    user.save(update_fields=['avatar'])  # uniquement la photo : ni le délai réservé ci-dessus ni les autres champs
    if old_name and old_name != user.avatar.name:
        transaction.on_commit(lambda: delete_stored_picture(old_name))
    messages.success(request, "Photo de profil mise à jour.")
    return redirect('account')
