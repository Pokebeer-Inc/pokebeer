from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, SetPasswordForm
from django.core.exceptions import ValidationError
from .auth_forms import ThrottledLoginMixin
from .services import notification_types
from .services.feedback import MAX_BODY_LENGTH as MAX_FEEDBACK_LENGTH
from .services.threads import plain_text
from .services.profile_pictures import process_profile_picture
from .services.quota import consume_quota
from .image_form import ProcessedImageMixin
from .services.official_images import process_official_image
from .services.tasting_photos import DAILY_LIMIT, QUOTA_SCOPE, process_tasting_photo
from .validators import MAX_TEXT_LENGTH, plain_text_validator, validate_siret, validate_tasting_date
from .models import BeerUser, Beer, Brewery, CustomNotebook, Drinks, Feedback, Bar, Report
from django.utils import timezone
from django.utils.text import slugify

from unfold.contrib.forms.widgets import ArrayWidget

INVALID_FIELD_STYLE = "border: 2px solid #ef4444;"

def clear_invalid_fields(form):
    """Vide et surligne les champs en erreur d'un formulaire lié ; les champs valides restent préremplis.

    À appeler après is_valid() : les erreurs déjà calculées sont conservées, seul le réaffichage change.
    """
    data = form.data.copy()
    for name in form.errors:
        field = form.fields.get(name)
        if field is None:
            continue
        data[form.add_prefix(name)] = ''
        field.widget.attrs['aria-invalid'] = 'true'
        field.widget.attrs['style'] = f"{field.widget.attrs.get('style', '')} {INVALID_FIELD_STYLE}".strip()
    form.data = data

def error_summary(*forms):
    """Liste lisible des erreurs ("Libellé : raison") de plusieurs formulaires."""
    lines = []
    for form in forms:
        for name, errors in form.errors.items():
            field = form.fields.get(name)
            label = field.label if field is not None and field.label else None
            lines += [f"{label} : {error}" if label else str(error) for error in errors]
    return lines

class UniqueUsernameMixin:
    """Refuse un pseudo déjà pris, sans tenir compte de la casse (« Alice » vaut « alice »), même lors d'un changement de pseudo."""

    def clean_username(self):
        username = self.cleaned_data['username']
        if BeerUser.objects.filter(username__iexact=username).exclude(pk=self.instance.pk).exists():
            raise ValidationError("Ce pseudo est déjà utilisé.", code='duplicate_username')
        return username

class UniqueEmailMixin:
    """Refuse une adresse déjà prise, sans tenir compte de la casse (« A@x.com » vaut « a@x.com »), même lors d'un changement d'adresse."""

    def clean_email(self):
        email = self.cleaned_data['email']
        if BeerUser.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError("Cet email est déjà utilisé par un autre membre.", code='duplicate_email')
        return email

class UserRegisterForm(UniqueUsernameMixin, UniqueEmailMixin, UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = BeerUser
        # Fields you want the user to fill in
        fields = ['username', 'email']

    def __init__(self, *args, **kwargs):
        super(UserRegisterForm, self).__init__(*args, **kwargs)
        
        # On définit explicitement les labels
        self.fields['username'].label = "Pseudo"
        self.fields['email'].label = "Adresse Email"
        
        # On applique les classes visuelles et le placeholder
        for field_name, field in self.fields.items():
            
            field.widget.attrs.update({
                'class': 'input input-bordered w-full bg-white/80 focus:bg-white transition-colors'
            })

class SuspensionNoticeLoginForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        'inactive': "Ce compte a été suspendu par la modération.",
    }

    def clean(self):
        # ModelBackend refuse les comptes inactifs comme un mauvais mot de passe : on précise la raison,
        # uniquement si le mot de passe est correct pour ne rien révéler à un tiers
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')
        if username and password:
            suspended = BeerUser.objects.filter(username=username, is_active=False).first()
            if suspended and suspended.check_password(password):
                raise ValidationError(self.error_messages['inactive'], code='inactive')
        return super().clean()


class UserLoginForm(ThrottledLoginMixin, SuspensionNoticeLoginForm):
    """Le blocage anti brute-force passe avant toute vérification du mot de passe."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # On définit explicitement les labels
        self.fields['username'].label = "Pseudo"
        self.fields['password'].label = "Mot de passe"
        
        # On applique les classes visuelles et le placeholder
        for field_name, field in self.fields.items():
            
            field.widget.attrs.update({
                'class': 'input input-bordered w-full bg-white/80 focus:bg-white transition-colors'
            })

class UserUpdateForm(UniqueUsernameMixin, UniqueEmailMixin, forms.ModelForm):
    class Meta:
        model = BeerUser
        fields = ['username', 'email', 'bio']
        labels = {
            'username': "Nom d'utilisateur",
            'email': "Adresse Email",
            'bio': "Ma Biographie"
        }
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Parlez-nous de vos goûts brassicoles...'})
        }

    def __init__(self, *args, **kwargs):
        super(UserUpdateForm, self).__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'form-control',
                'style': 'width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; margin-bottom: 10px;'
            })

class ProfilePictureForm(forms.ModelForm):
    """Seul champ modifiable : la photo ; le fichier est validé et ré-encodé avant d'être stocké."""
    avatar = forms.ImageField(required=True, label="Photo de profil", widget=forms.FileInput(attrs={'accept': ', '.join(['image/jpeg', 'image/png', 'image/webp'])}))

    class Meta:
        model = BeerUser
        fields = ['avatar']

    def clean_avatar(self):
        return process_profile_picture(self.cleaned_data['avatar'])

class ProSettingsForm(forms.ModelForm):
    show_establishments = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'toggle toggle-primary toggle-sm'})
    )

    class Meta:
        model = BeerUser
        fields = ['show_establishments']
    
class ProUserForm(UniqueUsernameMixin, UniqueEmailMixin, forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'input input-bordered w-full bg-white'}), 
        label="Mot de passe"
    )
    class Meta:
        model = BeerUser
        fields = ['username', 'email']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'input input-bordered w-full bg-white'}),
            'email': forms.EmailInput(attrs={'class': 'input input-bordered w-full bg-white'}),
        }

    def _post_clean(self):
        # Après la construction de l'instance : les validateurs comparent le mot de passe au pseudo et à l'email saisis
        super()._post_clean()
        password = self.cleaned_data.get('password')
        if password:
            try:
                password_validation.validate_password(password, self.instance)
            except ValidationError as error:
                self.add_error('password', error)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user

PRO_FIELDS = ['name', 'siret', 'description', 'address', 'phone', 'email', 'website', 'instagram', 'facebook', 'image']

class BarProForm(ProcessedImageMixin, forms.ModelForm):
    image_processors = {'image': process_official_image}
    siret = forms.CharField(max_length=14, min_length=14, required=True, validators=[validate_siret], label="Numéro SIRET (14 chiffres)", widget=forms.TextInput(attrs={'class': 'input input-bordered w-full bg-white', 'placeholder': 'Ex: 12345678901234'}))
    
    class Meta:
        model = Bar
        fields = PRO_FIELDS
        widgets = {field: forms.TextInput(attrs={'class': 'input input-bordered w-full bg-white'}) for field in PRO_FIELDS if field not in ['description', 'image', 'siret']}
        widgets['description'] = forms.Textarea(attrs={'class': 'textarea textarea-bordered w-full bg-white', 'rows': 3})
        
    def __init__(self, *args, **kwargs):
        super(BarProForm, self).__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get('class', '')
            
            field.widget.attrs.update({
                'class': f'form-control placeholder:text-gray-400 {existing_classes}'.strip()
            })

class BreweryProForm(ProcessedImageMixin, forms.ModelForm):
    image_processors = {'image': process_official_image}
    siret = forms.CharField(max_length=14, min_length=14, required=True, validators=[validate_siret], label="Numéro SIRET (14 chiffres)", widget=forms.TextInput(attrs={'class': 'input input-bordered w-full bg-white', 'placeholder': 'Ex: 12345678901234'}))
    
    class Meta:
        model = Brewery
        fields = PRO_FIELDS
        widgets = {field: forms.TextInput(attrs={'class': 'input input-bordered w-full bg-white'}) for field in PRO_FIELDS if field not in ['description', 'image', 'siret']}
        widgets['description'] = forms.Textarea(attrs={'class': 'textarea textarea-bordered w-full bg-white', 'rows': 3})
        
    def __init__(self, *args, **kwargs):
        super(BreweryProForm, self).__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get('class', '')
            
            field.widget.attrs.update({
                'class': f'form-control placeholder:text-gray-400 {existing_classes}'.strip()
            })
            
PLACE_EDIT_FIELDS = ['name', 'description', 'address', 'phone', 'email', 'website', 'instagram', 'facebook', 'image']

def _place_edit_widgets():
    input_class = 'input input-bordered w-full bg-white'
    return {
        'name': forms.TextInput(attrs={'class': input_class}),
        'address': forms.TextInput(attrs={'class': input_class}),
        'phone': forms.TextInput(attrs={'class': input_class}),
        'email': forms.EmailInput(attrs={'class': input_class}),
        'website': forms.URLInput(attrs={'class': input_class}),
        'instagram': forms.URLInput(attrs={'class': input_class}),
        'facebook': forms.URLInput(attrs={'class': input_class}),
        'description': forms.Textarea(attrs={'class': 'textarea textarea-bordered w-full bg-white', 'rows': 4}),
    }

class BreweryEditForm(ProcessedImageMixin, forms.ModelForm):
    image_processors = {'image': process_official_image}
    class Meta:
        model = Brewery
        fields = PLACE_EDIT_FIELDS
        widgets = _place_edit_widgets()

class BarEditForm(ProcessedImageMixin, forms.ModelForm):
    image_processors = {'image': process_official_image}
    class Meta:
        model = Bar
        fields = PLACE_EDIT_FIELDS
        widgets = _place_edit_widgets()

class BeerForm(ProcessedImageMixin, forms.ModelForm):
    image_processors = {'image': process_official_image}

    brewery_name = forms.CharField(
        label='Brasserie', max_length=150, validators=[plain_text_validator],
        help_text="Tapez le nom. Si elle n'existe pas, elle sera créée.",
        widget=forms.TextInput(attrs={'autocomplete': 'off'})
    )

    class Meta:
        model = Beer
        fields = ['name', 'brewery_name', 'style', 'description', 'bitterness', 'degree', 'image']
        labels = {
            'name': 'Nom de la bière',
            'description': 'Description officielle (Optionnel)',
            'bitterness': 'IBU (Optionnel)',
            'degree': 'Alcool (%)',
            'style': 'Style de bière (Optionnel)',
            'image': 'Photo de la bière',
        }
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Historique, arômes selon le brasseur...'}),
            'name': forms.TextInput(attrs={'autocomplete': 'off', 'placeholder': 'Ex: Punk IPA'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        
        if 'instance' in kwargs and kwargs['instance'] and kwargs['instance'].brewery_id:
            initial = kwargs.setdefault('initial', {})
            initial['brewery_name'] = kwargs['instance'].brewery_id.name
            
        super(BeerForm, self).__init__(*args, **kwargs)
        
        # Le champ image n'est proposé qu'à ceux qui ont le droit de la modifier
        if not self.may_edit_image(self.user, self.instance):
            self.drop_image_field('image')

        for field_name, field in self.fields.items():
            existing_classes = field.widget.attrs.get('class', '')
            # L'image est gérée par le composant partials/image_field.html
            if field_name not in ('image', 'remove_image'):
                field.widget.attrs.update({
                    'class': f'form-control placeholder:text-gray-400 {existing_classes}'.strip(),
                    'style': 'width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box;'
                })

    @staticmethod
    def may_edit_image(user, beer):
        """À la création, l'auteur de la bière peut l'illustrer. Ensuite : le gérant de sa brasserie, ou son créateur tant que
        le staff ne l'a pas vérifiée (la fiche vérifiée est alors garantie par le staff)."""
        if not user:
            return False
        if not beer.pk:
            return True
        if beer.brewery_id and beer.brewery_id.managers.filter(id=user.id).exists():
            return True
        return beer.added_by_id == user.id and not beer.is_verified

    def save(self, user=None, commit=True):
        beer = super().save(commit=False)
        b_name = self.cleaned_data['brewery_name']
        brewery, created = Brewery.objects.get_or_create(
            name__iexact=b_name,
            defaults={'name': b_name, 'description': 'Ajoutée automatiquement'}
        )
        beer.brewery_id = brewery
        
        if user:
            beer.added_by = user
            
        if commit:
            beer.save()
            self.delete_replaced_images()
        return beer
    
    def clean_name(self):
        """Bouclier anti-doublon insensible à la casse, espaces, et accents"""
        name = self.cleaned_data.get('name')
        if name:
            # On transforme le nom tapé en slug (ex: "Pünk I.P.A " devient "punk-ipa")
            normalized_name = slugify(name)
            # On compare les noms normalisés et non les slugs : une bière recréée après suppression reçoit un slug suffixé
            # ("punk-ipa-1"). Les bières supprimées sont ignorées, ainsi que la bière en cours de modification.
            candidates = Beer.objects.filter(slug__startswith=normalized_name, is_deleted=False).exclude(pk=self.instance.pk)
            existing_beer = next((beer for beer in candidates if slugify(beer.name) == normalized_name), None)
            if existing_beer:
                raise forms.ValidationError(f"Cette bière existe déjà sous le nom '{existing_beer.name}'")
        return name
    
    def clean_style(self):
        style = self.cleaned_data.get('style')
        if style:
            # Sépare par la virgule, enlève les espaces inutiles, et met une majuscule à chaque style
            styles = [s.strip().capitalize() for s in style.split(',') if s.strip()]
            # Reconstruit une belle chaîne "Style 1, Style 2"
            return ", ".join(styles)
        return style
    
class CustomNotebookForm(forms.ModelForm):
    class Meta:
        model = CustomNotebook
        fields = ['title', 'description']
        labels = {'title': "Titre", 'description': "Description"}

class BeerSpotForm(forms.Form):
    """Validation des champs envoyés par la modale de la carte (création et modification d'un lieu)."""
    spot_slug = forms.SlugField(required=False, max_length=150, label="Lieu")
    title = forms.CharField(max_length=150, label="Titre")
    description = forms.CharField(required=False, max_length=MAX_TEXT_LENGTH, label="Description")
    date = forms.DateField(required=False, label="Date", validators=[validate_tasting_date])
    # FloatField refuse aussi NaN et l'infini
    lat = forms.FloatField(min_value=-90, max_value=90, label="Latitude")
    lng = forms.FloatField(min_value=-180, max_value=180, label="Longitude")

class DrinkForm(ProcessedImageMixin, forms.ModelForm):
    """Note, commentaire et photo facultative d'une dégustation.

    La photo envoyée est validée et ré-encodée avant stockage ; `remove_photo` coché retire celle qui existe.
    `user` (le membre qui envoie) active le quota quotidien d'envois de photos.
    """
    image_processors = {'photo': process_tasting_photo}
    photo = forms.ImageField(required=False, label="Photo")

    class Meta:
        model = Drinks
        fields = ['date', 'note', 'comment', 'photo']
        labels = {
            'date': 'Date de dégustation',
            'note': 'Note (sur 10)',
            'comment': 'Mon avis personnel'
        }
        widgets = {
            'date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'comment': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Votre expérience, vos impressions en toute subjectivité...', 'class': 'textarea textarea-bordered w-full'}),
            'note': forms.NumberInput(attrs={'min': 0, 'max': 10}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super(DrinkForm, self).__init__(*args, **kwargs)
        self.user = user
        self.fields['note'].required = False
        for name, field in self.fields.items():
            if name in ('photo', 'remove_photo'):
                continue  # gérés par le composant partials/image_field.html
            field.widget.attrs.update({
                'class': 'form-control placeholder:text-gray-400',
                'style': 'width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; margin-bottom: 10px;'
            })

    def clean_date(self):
        date = self.cleaned_data['date']
        if not self.instance.pk or date != self.instance.date:  # une date déjà enregistrée n'est pas revalidée à chaque modification
            validate_tasting_date(date)
        return date

    def _post_clean(self):
        super()._post_clean()
        # Le quota n'est consommé qu'une fois tout le formulaire valide : une erreur de saisie ne fait pas perdre d'envoi
        if not self.errors and self.user and self.uploaded_image('photo'):
            if not consume_quota(self.user, DAILY_LIMIT, QUOTA_SCOPE):
                self.add_error('photo', ValidationError("Limite quotidienne d'envois de photos atteinte, réessayez demain.", code='quota'))

class FeedbackForm(forms.Form):
    """Premier message d'un échange avec l'équipe."""
    message = forms.CharField(
        max_length=MAX_FEEDBACK_LENGTH, label="Votre suggestion, remarque ou bug",
        widget=forms.Textarea(attrs={
            'rows': 4, 'maxlength': MAX_FEEDBACK_LENGTH, 'class': 'form-control',
            'style': 'width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; margin-bottom: 10px;',
        }),
    )


class FeedbackReplyForm(forms.Form):
    """Message du membre dans un échange existant."""
    body = forms.CharField(
        max_length=MAX_FEEDBACK_LENGTH, label="Votre message",
        widget=forms.Textarea(attrs={'rows': 3, 'maxlength': MAX_FEEDBACK_LENGTH, 'placeholder': "Répondre à l'équipe…"}),
    )

class NotificationPreferenceForm(forms.ModelForm):
    class Meta:
        model = BeerUser
        fields = ['notif_global', *notification_types.CATEGORY_FIELDS]
        widgets = {
            'notif_global': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary'}),
            **{field: forms.CheckboxInput(attrs={'class': 'toggle toggle-sm toggle-primary'}) for field in notification_types.CATEGORY_FIELDS},
        }


class ReportForm(forms.Form):
    """Signalement envoyé depuis les modales (bière, avis, profil, brasserie)."""
    TARGET_MODELS = {'beer': Beer, 'drink': Drinks, 'user': BeerUser, 'brewery': Brewery}
    # Champ public qui désigne la cible : le slug, ou le pseudo pour un membre
    TARGET_LOOKUPS = {'beer': 'slug', 'drink': 'slug', 'user': 'username', 'brewery': 'slug'}
    DESCRIPTION_MIN_LENGTH = 10
    DESCRIPTION_MAX_LENGTH = 1000

    item_type = forms.ChoiceField(choices=[(key, key) for key in TARGET_MODELS], label="Élément signalé")
    item_ref = forms.CharField(max_length=150, label="Élément signalé")
    reason = forms.ChoiceField(choices=Report.REASON_CHOICES, label="Raison")
    description = forms.CharField(min_length=DESCRIPTION_MIN_LENGTH, max_length=DESCRIPTION_MAX_LENGTH, label="Description")

    def __init__(self, *args, reporter, **kwargs):
        self.reporter = reporter
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        since = timezone.now() - timedelta(hours=24)
        if Report.objects.filter(reporter=self.reporter, created_at__gte=since).count() >= settings.REPORT_DAILY_LIMIT:
            raise ValidationError(f"Vous avez atteint la limite de {settings.REPORT_DAILY_LIMIT} signalements par 24 heures. Réessayez plus tard.")

        item_type, item_ref = cleaned_data.get('item_type'), cleaned_data.get('item_ref')
        if not (item_type and item_ref):
            return cleaned_data

        target = self.TARGET_MODELS[item_type].objects.filter(**{self.TARGET_LOOKUPS[item_type]: item_ref}).first()
        if target is None:
            self.add_error('item_ref', "L'élément signalé n'existe pas ou plus.")
        elif target == self.reporter or (item_type == 'drink' and target.drinker_id_id == self.reporter.pk):
            self.add_error('item_ref', "Vous ne pouvez pas signaler votre propre profil ou votre propre avis.")
        else:
            cleaned_data['target'] = target
        return cleaned_data

    def save(self):
        item_type = self.cleaned_data['item_type']
        return Report.objects.create(
            reporter=self.reporter,
            reason=self.cleaned_data['reason'],
            description=self.cleaned_data['description'],
            **{f'reported_{item_type}': self.cleaned_data['target']},
        )

class ReportAdminForm(forms.ModelForm):
    class Meta:
        model = Report
        fields = (
            "status",
            "admin_response",
        )

        widgets = {
            "admin_response": forms.Textarea(attrs={"rows": 5}),
        }
        labels = {"admin_response": "Réponse au membre (texte brut)"}

    def clean_admin_response(self):
        return plain_text(self.cleaned_data.get("admin_response"))


class FeedbackAdminForm(forms.ModelForm):
    """Côté équipe : le statut et un champ « réponse » (qui ajoute un message à l'échange, il n'écrase rien)."""
    reply = forms.CharField(
        required=False, max_length=MAX_FEEDBACK_LENGTH, label="Répondre au membre",
        widget=forms.Textarea(attrs={'rows': 4}), help_text="Envoyée au membre, qui est notifié.",
    )

    class Meta:
        model = Feedback
        fields = ("status",)



FIELD_CLASS = 'input input-bordered w-full bg-white/80 focus:bg-white transition-colors'


class StyledFieldsMixin:
    """Applique le style des champs de saisie du site à tous les champs du formulaire."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = FIELD_CLASS


class PasswordResetRequestForm(StyledFieldsMixin, forms.Form):
    email = forms.EmailField(label="Adresse e-mail du compte", max_length=254, widget=forms.EmailInput(attrs={'autocomplete': 'email'}))


class NewPasswordForm(StyledFieldsMixin, SetPasswordForm):
    """Nouveau mot de passe (règles de robustesse du site) saisi après le clic sur le lien reçu par e-mail."""

    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['autocomplete'] = 'new-password'
