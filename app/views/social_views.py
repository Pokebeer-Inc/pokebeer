from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import Http404, JsonResponse
from django.contrib import messages
from django.db.models import Max, Q, Count
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
import json
from urllib.parse import urlsplit

from ..models import AccountDeletion, BeerUser, UserFollow, Beer, Drinks, UserBlock, DrinkReaction
from ..forms import UsernameForm, UserUpdateForm, FeedbackForm, MarketingConsentForm, NotificationPreferenceForm, ProSettingsForm
from .utils import get_user_achievements, check_and_notify_achievements, previous_page
from .services.stats import get_user_statistics, get_top_beers_data
from ..services.feedback import FeedbackError, open_thread
from ..services import password_reset
from ..services.inactivity import delete_account
from ..services.notifications import notify
from ..services.throttle import USERNAME_ATTEMPTS, USERNAME_CHANGES

SETTINGS_SECTIONS = {
    'profile': "Informations et bio",
    'notifications': "Notifications et e-mails",
    'privacy': "Visibilité et confidentialité",
    'security': "Mot de passe",
    'team': "Écrire à l'équipe",
}

@login_required(login_url='login')
def account_view(request, section=None):
    """Profil (page unique) et réglages : chaque section de réglages a sa page, avec les mêmes formulaires qu'avant."""
    if section is not None and section not in SETTINGS_SECTIONS:
        raise Http404
    user = request.user
    done = lambda: redirect('account_settings', section=section) if section else redirect('account')
    profile_form = UserUpdateForm(instance=user)
    password_form = PasswordChangeForm(user=user)
    feedback_form = FeedbackForm()
    notif_form = NotificationPreferenceForm(instance=user)
    marketing_form = MarketingConsentForm(user=user)
    pro_settings_form = ProSettingsForm(instance=user)
    
    if request.method == 'POST':
        if 'btn_profile' in request.POST:
            profile_form = UserUpdateForm(request.POST, instance=user)
            if profile_form.is_valid():
                profile_form.save()
                
                check_and_notify_achievements(request.user)
                
                messages.success(request, "Profil mis à jour.")
                return done()
        
        elif 'btn_pro_settings' in request.POST:
            pro_settings_form = ProSettingsForm(request.POST, instance=user)
            if pro_settings_form.is_valid():
                pro_settings_form.save()
                messages.success(request, "Paramètres de confidentialité mis à jour.")
                return done()
            else:
                messages.error(request, "Erreur dans le changement de préférence de la visibilité.")

        elif 'btn_password' in request.POST:
            password_form = PasswordChangeForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                password_reset.notify_password_changed(user)
                messages.success(request, "Votre mot de passe a été changé avec succès !")
                return done()
            else:
                messages.error(request, "Erreur dans le changement de mot de passe.")
                
        # Gestion du feedback
        elif 'btn_feedback' in request.POST:
            feedback_form = FeedbackForm(request.POST)
            if feedback_form.is_valid():
                try:
                    thread = open_thread(user, feedback_form.cleaned_data['message'])
                except FeedbackError as error:
                    messages.error(request, str(error))
                else:
                    messages.success(request, "Merci ! Votre message a bien été envoyé à l'équipe.")
                    return redirect('feedback_thread', feedback_slug=thread.slug)
            else:
                messages.error(request, "Erreur dans l'envoi de votre feedback.")
        
        # Gestion des préférences de notifications
        elif 'btn_notifs' in request.POST:
            notif_form = NotificationPreferenceForm(request.POST, instance=user)
            if notif_form.is_valid():
                notif_form.save()
                messages.success(request, "Préférences de notifications mises à jour.")
                return done()
            else:
                messages.error(request, "Erreur dans le changement de préférence des notifications.")

        # Accord aux e-mails promotionnels
        elif 'btn_marketing' in request.POST:
            marketing_form = MarketingConsentForm(request.POST, user=user)
            if marketing_form.is_valid():
                marketing_form.save()
                messages.success(request, "Préférence d'e-mails mise à jour.")
                return done()

    if section:
        return render(request, 'account_settings.html', {
            'section': section, 'section_title': SETTINGS_SECTIONS[section],
            'profile_form': profile_form, 'password_form': password_form, 'feedback_form': feedback_form,
            'notif_form': notif_form, 'marketing_form': marketing_form, 'pro_settings_form': pro_settings_form,
            'feedback_threads_count': user.feedbacks.count(),
        })

    # 2. Requêtes de base
    my_drinks = Drinks.objects.filter(drinker_id=user).select_related('beer_id', 'beer_id__brewery_id').order_by('-date')
    
    # Social
    followers = UserFollow.objects.filter(followed=user, follower__is_active=True).select_related('follower')
    following = UserFollow.objects.filter(follower=user, followed__is_active=True).select_related('followed')

    # 3. Calcul des Statistiques
    stats = get_user_statistics(my_drinks)
    top_beers_data = get_top_beers_data(user, my_drinks, include_empty=True)
        
    # Récupération des trophées débloqués
    all_achievements, level_data = get_user_achievements(user)
    unlocked_achievements = [a for a in all_achievements if a['tier_level'] > 0]
        
    managed_breweries = list(user.managed_breweries.all())
    managed_bars = list(user.managed_bars.all())
    context = {
        'managed_breweries': managed_breweries,
        'managed_bars': managed_bars,
        'show_establishments_section': bool(managed_breweries or managed_bars or user.is_bartender or user.is_brewer),
        'profile_form': profile_form,
        'password_form': password_form,
        'feedback_form': feedback_form,
        'notif_form': notif_form,
        'pending_claims': user.claims.filter(status='pending').select_related('brewery', 'bar'),
        'marketing_form': marketing_form,
        'pro_settings_form': pro_settings_form,
        'feedback_threads_count': user.feedbacks.count(),
        'my_drinks': my_drinks,
        'followers': followers,
        'following': following,
        'top_beers_data': top_beers_data,
        'unlocked_achievements': unlocked_achievements,
        'level': level_data['current_level'],
        **stats
    }
    return render(request, 'account.html', context)

@login_required(login_url='login')
def delete_account_view(request):
    """Supprime le compte de l'utilisateur et ses données associées (sauf les bières du catalogue)."""
    if request.method == 'POST':
        user = request.user
        # 1. On déconnecte l'utilisateur pour invalider sa session
        logout(request)
        # 2. On supprime l'utilisateur (Django gère les CASCADE et les SET_NULL automatiquement) et on en garde la trace
        delete_account(user, AccountDeletion.Reason.SELF)
        
        messages.success(request, "Votre compte et toutes vos données personnelles ont été supprimés. Au revoir !")
        return redirect('index')
        
    return redirect('account')

@login_required(login_url='login')
def public_profile_view(request, username):
    """Affiche le profil public d'un autre utilisateur."""
    # Si l'utilisateur clique sur son propre profil, on le redirige vers son compte privé
    if request.user.username == username:
        return redirect('account')
        
    profile_user = get_object_or_404(
        BeerUser.objects.filter(is_active=True).select_related('top_beer_1', 'top_beer_2', 'top_beer_3'), 
        username=username
    )
    
    # Vérification blocage mutuel
    if UserBlock.objects.filter(Q(blocker=request.user, blocked=profile_user) | 
                                Q(blocker=profile_user, blocked=request.user)).exists():
        messages.error(request, "Ce profil n'est pas accessible.")
        return redirect('index')
    
    # Toutes les dégustations servent aux statistiques ; seule la liste de l'onglet affiché est chargée (10 premières)
    user_drinks = Drinks.objects.filter(drinker_id=profile_user).select_related('beer_id', 'beer_id__brewery_id').order_by('-date')

    requested_tab = {'degustations': 'tastings', 'ajouts': 'additions'}.get(request.GET.get('tab'), request.GET.get('tab'))  # anciens noms français acceptés
    active_tab = requested_tab if requested_tab in ('tastings', 'additions') else 'tastings'
    shown_drinks, added_beers = [], []
    if active_tab == 'tastings':
        shown_drinks = list(user_drinks[:10])
    else:
        added_beers = list(Beer.objects.filter(added_by=profile_user).annotate(
            user_note=Max('drinks__note', filter=Q(drinks__drinker_id=profile_user)),
            count_rating=Count('drinks')
        ).order_by('-id')[:10])

    # Social
    followers = UserFollow.objects.filter(followed=profile_user, follower__is_active=True).select_related('follower')
    following = UserFollow.objects.filter(follower=profile_user, followed__is_active=True).select_related('followed')

    # Est-ce que JE (l'utilisateur connecté) suis cette personne ?
    is_following = followers.filter(follower=request.user).exists()

    # Calcul des Statistiques
    stats = get_user_statistics(user_drinks)
    top_beers_data = get_top_beers_data(profile_user, user_drinks, include_empty=False)

    all_achievements, level_data = get_user_achievements(profile_user)
    unlocked_achievements = [a for a in all_achievements if a['tier_level'] > 0]

    # Retour vers la page d'origine ; si c'est ce profil lui-même (rechargé par les puces), vers la recherche
    back_url = previous_page(request)
    if urlsplit(back_url).path == request.path:
        back_url = reverse('index')

    show_establishments = profile_user.has_public_establishments
    context = {
        'profile_user': profile_user,
        'active_tab': active_tab,
        'user_drinks': shown_drinks,
        'user_added_beers': added_beers,
        'followers': followers,
        'following': following,
        'is_following': is_following,
        'top_beers_data': top_beers_data,
        'unlocked_achievements': unlocked_achievements,
        'level': level_data['current_level'],
        'show_establishments': show_establishments,
        'managed_breweries': list(profile_user.my_breweries) if show_establishments else [],
        'managed_bars': list(profile_user.my_bars) if show_establishments else [],
        'back_url': back_url,
        **stats
    }
    return render(request, 'public_profile.html', context)

@require_POST
@login_required(login_url='login')
def follow_user(request, username):
    """Gère l'action de s'abonner ou se désabonner."""
    user_to_follow = get_object_or_404(BeerUser, username=username, is_active=True)
    
    if request.user != user_to_follow:
        follow_record = UserFollow.objects.filter(follower=request.user, followed=user_to_follow)
        if follow_record.exists():
            follow_record.delete() # Se désabonner
            messages.info(request, f"Vous ne suivez plus {username}.")
        else:
            UserFollow.objects.create(follower=request.user, followed=user_to_follow) # S'abonner
            notify('follow', [user_to_follow], sender=request.user)
            messages.success(request, f"Vous suivez maintenant {username} !")
            
    check_and_notify_achievements(request.user)
    return redirect(previous_page(request))

@login_required(login_url='login')
def remove_follower(request, username):
    """Permet à un utilisateur de supprimer quelqu'un de ses abonnés."""
    follower_to_remove = get_object_or_404(BeerUser, username=username)
    
    # On cherche le lien où follower_to_remove suit request.user
    follow_record = UserFollow.objects.filter(follower=follower_to_remove, followed=request.user)
    
    if request.method == 'POST' and follow_record.exists():
        follow_record.delete()
        messages.info(request, f"{username} a été retiré de vos abonnés.")
        
    return redirect(previous_page(request, 'account'))

@require_POST
@login_required(login_url='login')
def toggle_reaction_view(request, drink_slug):
    """API pour liker/disliker un avis."""
    try:
        data = json.loads(request.body)
        is_like = data.get('is_like')
        
        drink = get_object_or_404(Drinks, slug=drink_slug)
        if drink.drinker_id == request.user:
            return JsonResponse({'success': False, 'error': "Vous ne pouvez pas réagir à votre propre avis."}, status=400)
            
        reaction, created = DrinkReaction.objects.get_or_create(
            user=request.user, 
            drink=drink, 
            defaults={'is_like': is_like}
        )
        
        current_reaction = is_like # On garde en mémoire l'état final
        
        # Logique : Bascule si déjà existant
        if not created:
            if reaction.is_like == is_like:
                reaction.delete() # Clic sur le même bouton = annulation
                current_reaction = None
            else:
                reaction.is_like = is_like
                reaction.save() # Changement d'avis (ex: passe de Like à Dislike)
                
                if is_like:
                    notify('drink_liked', [drink.drinker_id], sender=request.user, beer=drink.beer_id)
        else:
            # Notification si c'est une nouvelle réaction et que c'est un Like
            if is_like:
                notify('drink_liked', [drink.drinker_id], sender=request.user, beer=drink.beer_id)
        
        # Vérification du trophée César
        check_and_notify_achievements(request.user)
        
        # Recalcul des scores exacts
        likes = drink.reactions.filter(is_like=True).count()
        dislikes = drink.reactions.filter(is_like=False).count()
        
        return JsonResponse({
            'success': True,
            'score': likes - dislikes,
            'likes': likes,
            'dislikes': dislikes,
            'current_reaction': current_reaction
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

@require_POST
@login_required(login_url='login')
def update_top_beer(request, slot):
    """Met à jour l'un des 3 slots du Top 3 de l'utilisateur."""
    if slot not in [1, 2, 3]:
        messages.error(request, "Emplacement invalide.")
        return redirect('account')

    beer_slug = request.POST.get('beer_slug')
    user = request.user

    if beer_slug:
        beer = get_object_or_404(Beer, slug=beer_slug)
        
        if (slot != 1 and user.top_beer_1_id == beer.id) or \
           (slot != 2 and user.top_beer_2_id == beer.id) or \
           (slot != 3 and user.top_beer_3_id == beer.id):
            messages.error(request, f"{beer.name} est déjà dans votre Top 3 !")
            return redirect('account')

        if slot == 1: user.top_beer_1 = beer
        elif slot == 2: user.top_beer_2 = beer
        elif slot == 3: user.top_beer_3 = beer
        messages.success(request, f"Bière ajoutée à votre Top {slot} !")
    else:
        # Si aucun slug n'est fourni, on vide l'emplacement
        if slot == 1: user.top_beer_1 = None
        elif slot == 2: user.top_beer_2 = None
        elif slot == 3: user.top_beer_3 = None
        messages.info(request, f"Emplacement Top {slot} vidé.")

    user.save()
    return redirect('account')

@require_POST
@login_required(login_url='login')
def reorder_top_beers(request):
    """API du glisser-déposer du Top 3 : `order` donne, pour chaque position, l'ancien emplacement qui vient s'y placer.

    Ex. [2, 3, 1] : la bière du 2 passe en 1, celle du 3 en 2, celle du 1 en 3. Seule une permutation de 1, 2, 3 est acceptée.
    """
    if len(request.body) > 200:
        return JsonResponse({'success': False, 'error': 'Requête invalide'}, status=400)
    try:
        order = json.loads(request.body).get('order')
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({'success': False, 'error': 'Requête invalide'}, status=400)
    if not (isinstance(order, list) and len(order) == 3 and all(type(slot) is int for slot in order) and sorted(order) == [1, 2, 3]):
        return JsonResponse({'success': False, 'error': 'Emplacements invalides'}, status=400)

    user = request.user
    current = {1: user.top_beer_1_id, 2: user.top_beer_2_id, 3: user.top_beer_3_id}
    user.top_beer_1_id, user.top_beer_2_id, user.top_beer_3_id = (current[slot] for slot in order)
    user.save(update_fields=['top_beer_1', 'top_beer_2', 'top_beer_3'])
    return JsonResponse({'success': True})


@require_POST
@login_required(login_url='login')
def update_username_view(request):
    """Change le pseudo du membre connecté (l'URL de son profil public change avec lui).

    Validation côté serveur uniquement : format, unicité sans casse, pseudos réservés (UsernameForm). Deux plafonds par
    membre : les essais (pour qu'on ne puisse pas sonder les pseudos libres) et les changements réellement faits.
    Répond en JSON pour la fenêtre de la page profil, par redirection sinon.
    """
    wants_json = request.headers.get('X-Requested-With') == 'fetch'
    key = f"user:{request.user.pk}"

    def refuse(message, status):
        if wants_json:
            return JsonResponse({'success': False, 'error': message}, status=status)
        messages.error(request, message)
        return redirect('account')

    if USERNAME_ATTEMPTS.exceeded(key) or USERNAME_CHANGES.exceeded(key):
        return refuse("Trop de changements de pseudo. Réessayez plus tard.", 429)
    USERNAME_ATTEMPTS.record(key)

    form = UsernameForm(request.POST, instance=request.user)
    if not form.is_valid():
        return refuse(" ".join(form.errors['username']) if 'username' in form.errors else "Pseudo invalide.", 400)

    if form.cleaned_data['username'] != form.initial['username']:
        form.save()
        USERNAME_CHANGES.record(key)
    if wants_json:
        return JsonResponse({'success': True, 'username': request.user.username})
    messages.success(request, "Pseudo mis à jour.")
    return redirect('account')


@login_required(login_url='login')
def settings_home_view(request):
    """Page des réglages : toutes les rubriques (informations, notifications, aide) et la déconnexion."""
    return render(request, 'account_settings_home.html', {'feedback_threads_count': request.user.feedbacks.count()})


@require_POST
@login_required(login_url='login')
def toggle_wishlist(request, beer_slug):
    """API pour ajouter/retirer une bière de la wishlist."""
    beer = get_object_or_404(Beer, slug=beer_slug)
    user = request.user
    
    if beer in user.wishlist_beers.all():
        user.wishlist_beers.remove(beer)
        is_in_wishlist = False
    else:
        user.wishlist_beers.add(beer)
        is_in_wishlist = True
        
        # Notification au créateur de la bière
        if beer.added_by and beer.added_by != user:
            notify('wishlist_added', [beer.added_by], sender=user, beer=beer)
        
    return JsonResponse({'success': True, 'is_in_wishlist': is_in_wishlist})

@login_required(login_url='login')
def achievements_view(request):
    """Page des trophées, hauts faits et cosmétiques."""
    achievements, level_data = get_user_achievements(request.user)
    
    context = {
        'achievements': achievements,
        'level_data': level_data,
    }
    return render(request, 'achievements.html', context)