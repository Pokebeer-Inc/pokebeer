from datetime import timedelta

from django import forms
from django.conf import settings
from django.urls import reverse_lazy
from django.contrib.auth import password_validation
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, SetPasswordForm
from django.core.exceptions import ValidationError
from .auth_forms import ThrottledLoginMixin
from .services.catalog import catalog_matching, ean
from .domain import notification_types
from .services.catalog import style_registry
from .services.messaging import marketing
from .services.establishments import postal_codes
from .services.support.feedback import MAX_BODY_LENGTH as MAX_FEEDBACK_LENGTH
from .services.support.threads import plain_text
from .services.members import identity
from .services.members.profile_pictures import process_profile_picture
from .services.protection.quota import consume_quota
from .image_form import ProcessedImageMixin
from .services.catalog.official_images import process_official_image
from .services.catalog.tasting_photos import DAILY_LIMIT, QUOTA_SCOPE, process_tasting_photo
from .validators import MAX_TEXT_LENGTH, OLDEST_BIRTH_YEAR, is_reserved_username, plain_text_validator, validate_adult_birth_date, validate_siret, validate_tasting_date
from .models import Bar, BarBeer, Beer, BeerUser, Brewery, CustomNotebook, Drinks, Feedback, Report
from django.utils import timezone


# Apparence des champs : classes de static/style/ui.css (aucun style en ligne, la présentation reste dans les feuilles de style)
PLAIN_INPUT_CLASS = 'form-control pb-plain-input'
INVALID_FIELD_CLASS = 'pb-field-invalid'

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
        field.widget.attrs['class'] = f"{field.widget.attrs.get('class', '')} {INVALID_FIELD_CLASS}".strip()
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
        if is_reserved_username(username) and username != (self.instance.username if self.instance.pk else None):
            raise ValidationError("Ce pseudo est réservé. Choisissez-en un autre.", code='reserved_username')
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
        super().__init__(*args, **kwargs)
        
        # On définit explicitement les labels
        self.fields['username'].label = "Pseudo"
        self.fields['email'].label = "Adresse Email"
        
        # On applique les classes visuelles et le placeholder
        for field in self.fields.values():
            
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
            if suspended is None:
                # Même coût qu'une vérification réelle : le temps de réponse ne révèle pas qu'un pseudo suspendu existe
                BeerUser().set_password(password)
            elif suspended.check_password(password):
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
        for field in self.fields.values():
            
            field.widget.attrs.update({
                'class': 'input input-bordered w-full bg-white/80 focus:bg-white transition-colors'
            })

class BirthDateForm(forms.ModelForm):
    """Date de naissance demandée juste après l'inscription : obligatoire, et celle d'une personne majeure (jamais montrée aux autres membres)."""

    class Meta:
        model = BeerUser
        fields = ['birth_date']
        labels = {'birth_date': "Date de naissance"}
        widgets = {'birth_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'autocomplete': 'bday'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields['birth_date']
        field.required = True
        field.error_messages['required'] = "Indiquez votre date de naissance pour continuer."
        field.error_messages['invalid'] = "Cette date de naissance n'est pas valide."
        field.widget.attrs.update({'min': f'{OLDEST_BIRTH_YEAR}-01-01', 'max': timezone.localdate().isoformat(), 'class': 'pb-input text-lg'})

    def clean_birth_date(self):
        birth_date = self.cleaned_data['birth_date']
        validate_adult_birth_date(birth_date)
        return birth_date


class GenderForm(forms.ModelForm):
    """Genre demandé après la date de naissance : facultatif (aucune réponse vaut « passer »)."""

    class Meta:
        model = BeerUser
        fields = ['gender']
        widgets = {'gender': forms.RadioSelect}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields['gender']
        field.required = False
        field.choices = [choice for choice in field.choices if choice[0] != '']  # pas de choix vide : on ne coche rien pour passer


class UsernameForm(UniqueUsernameMixin, forms.ModelForm):
    """Changement de pseudo seul : mêmes règles que l'inscription (format, unicité sans casse, pseudos réservés)."""

    class Meta:
        model = BeerUser
        fields = ['username']
        labels = {'username': "Pseudo"}


class IdentityConfirmationMixin:
    """Champ `confirmation` d'une action sensible : mot de passe actuel, ou pseudo pour un compte sans mot de passe (connexion Google).

    La vérification (et la limite d'essais) est celle de services/members/identity.py."""

    def add_confirmation_field(self, user, required=True, help_text=''):
        self.confirming_user = user
        if identity.uses_password(user):
            field = forms.CharField(label="Mot de passe actuel", strip=False, required=required, help_text=help_text,
                                    widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))
        else:
            field = forms.CharField(label="Votre pseudo", max_length=150, required=required, help_text=help_text or "Retapez votre pseudo pour confirmer.",
                                    widget=forms.TextInput(attrs={'autocomplete': 'off', 'autocapitalize': 'none', 'spellcheck': 'false'}))
        self.fields['confirmation'] = field

    def confirm_identity(self):
        """Vrai si l'identité est confirmée ; sinon l'erreur est ajoutée au champ `confirmation`."""
        try:
            identity.confirm(self.confirming_user, self.cleaned_data.get('confirmation'))
        except identity.IdentityNotConfirmed as error:
            self.add_error('confirmation', str(error))
            return False
        return True


class UserUpdateForm(UniqueEmailMixin, IdentityConfirmationMixin, forms.ModelForm):
    """Adresse e-mail et biographie. Le pseudo se change à part (update_username_view, limité en débit).

    Changer d'adresse exige le mot de passe actuel ; l'adresse d'un compte sans mot de passe (connexion Google) n'est pas modifiable."""

    class Meta:
        model = BeerUser
        fields = ['email', 'bio']
        labels = {
            'email': "Adresse Email",
            'bio': "Ma Biographie"
        }
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Parlez-nous de vos goûts brassicoles...'})
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if identity.uses_password(self.instance):
            self.add_confirmation_field(self.instance, required=False, help_text="Requis uniquement pour changer d'adresse e-mail.")
        else:
            self.fields['email'].disabled = True  # Django ignore alors toute valeur envoyée pour ce champ
            self.fields['email'].help_text = "Adresse de votre compte Google : elle ne peut pas être modifiée ici."
        for field in self.fields.values():
            field.widget.attrs['class'] = PLAIN_INPUT_CLASS

    @property
    def email_changed(self):
        return 'email' in self.changed_data

    def clean(self):
        cleaned_data = super().clean()
        if self.email_changed and 'email' not in self.errors:
            if not cleaned_data.get('confirmation'):
                self.add_error('confirmation', "Saisissez votre mot de passe actuel pour changer d'adresse e-mail.")
            else:
                self.confirm_identity()
        return cleaned_data


class AccountDeletionForm(IdentityConfirmationMixin, forms.Form):
    """Suppression du compte : confirmée par le mot de passe actuel, ou par le pseudo pour un compte sans mot de passe."""

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_confirmation_field(user)
        self.fields['confirmation'].widget.attrs['class'] = 'pb-input w-full'

    def clean(self):
        cleaned_data = super().clean()
        if not self.errors:
            self.confirm_identity()
        return cleaned_data

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
    
class StatsSettingsForm(forms.ModelForm):
    """Opposition aux statistiques anonymes d'âge et de genre : cochée par défaut, modifiable à tout moment."""
    demographic_stats = forms.BooleanField(
        required=False, label="Compter mon âge et mon genre dans les statistiques anonymes",
        widget=forms.CheckboxInput(attrs={'class': 'toggle toggle-primary toggle-sm'}),
    )

    class Meta:
        model = BeerUser
        fields = ['demographic_stats']


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

ADDRESS_FIELDS = ['street', 'postal_code', 'city']
PRO_FIELDS = ['name', 'siret', 'description', *ADDRESS_FIELDS, 'phone', 'email', 'website', 'instagram', 'facebook', 'image']


def address_widgets(css_class, group='address'):
    """Rue, code postal et ville : le script postal_code.js relie les deux derniers (la ville se déduit du code postal)."""
    return {
        'street': forms.TextInput(attrs={'class': css_class, 'autocomplete': 'street-address'}),
        'postal_code': forms.TextInput(attrs={'class': css_class, 'inputmode': 'numeric', 'maxlength': 5, 'pattern': r'\d{5}', 'autocomplete': 'postal-code', 'data-postal-group': group, 'data-postal-input': '', 'data-postal-url': reverse_lazy('postal_code_lookup')}),
        'city': forms.TextInput(attrs={'class': css_class, 'autocomplete': 'address-level2', 'list': f'cities-{group}', 'data-postal-group': group, 'data-city-input': ''}),
    }


class PostalAddressFormMixin:
    """La ville d'un établissement vient de son code postal (services/establishments/postal_codes.py) : jamais une ville inventée ou en désaccord avec le code."""

    def clean(self):
        data = super().clean()
        if self.errors.get('postal_code') or self.errors.get('city'):
            return data
        try:
            resolution = postal_codes.resolve(data.get('postal_code', ''), data.get('city', ''))
        except postal_codes.PostalCodeError as error:
            self.add_error(error.field, str(error))
            return data
        data['postal_code'], data['city'] = resolution.postal_code, resolution.city
        return data


class ProPlaceForm(PostalAddressFormMixin, ProcessedImageMixin, forms.ModelForm):
    """Fiche d'un établissement à l'inscription d'un gérant : commune à Bar et Brasserie, seul le modèle change."""
    image_processors = {'image': process_official_image}
    siret = forms.CharField(max_length=14, min_length=14, required=True, validators=[validate_siret], label="Numéro SIRET (14 chiffres)", widget=forms.TextInput(attrs={'class': 'input input-bordered w-full bg-white', 'placeholder': 'Ex: 12345678901234'}))

    class Meta:
        fields = PRO_FIELDS
        widgets = {field: forms.TextInput(attrs={'class': 'input input-bordered w-full bg-white'}) for field in PRO_FIELDS if field not in ['description', 'image', 'siret', *ADDRESS_FIELDS]}
        widgets.update(address_widgets('input input-bordered w-full bg-white', 'pro'))
        widgets['description'] = forms.Textarea(attrs={'class': 'textarea textarea-bordered w-full bg-white', 'rows': 3})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get('class', '')
            field.widget.attrs.update({'class': f'form-control placeholder:text-gray-400 {existing_classes}'.strip()})
        self.fields['postal_code'].required = True  # c'est elle qui distingue deux établissements de même nom


    def validate_unique(self):
        """Le SIRET d'une fiche existante n'est pas une erreur ici : l'inscription devient alors une demande de gestion de cette fiche
        (services/establishments/claims.py). Le SIRET n'est rattaché à une fiche qu'à l'acceptation de la demande."""
        exclude = self._get_validation_exclusions() | {'siret'}
        try:
            self.instance.validate_unique(exclude=exclude)
        except ValidationError as error:
            self._update_errors(error)


class BarProForm(ProPlaceForm):
    class Meta(ProPlaceForm.Meta):
        model = Bar


class BreweryProForm(ProPlaceForm):
    class Meta(ProPlaceForm.Meta):
        model = Brewery


class ClaimForm(forms.Form):
    """Demande de gestion d'une fiche existante (bouton « Revendiquer cette fiche »)."""
    siret = forms.CharField(label="SIRET de l'établissement (14 chiffres)", max_length=20, widget=forms.TextInput(attrs={'inputmode': 'numeric', 'placeholder': 'Ex : 12345678901234', 'class': 'input input-bordered w-full bg-white'}))
    message = forms.CharField(
        label="Message à l'équipe (facultatif)", required=False, max_length=500, validators=[plain_text_validator],
        help_text="Quelques mots sur votre rôle, ou un moyen de vous joindre.",
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'textarea textarea-bordered w-full bg-white'}),
    )


PLACE_EDIT_FIELDS = ['name', 'description', *ADDRESS_FIELDS, 'phone', 'email', 'website', 'instagram', 'facebook', 'image']

def _place_edit_widgets():
    input_class = 'input input-bordered w-full bg-white'
    return {
        'name': forms.TextInput(attrs={'class': input_class}),
        **address_widgets(input_class, 'edit'),
        'phone': forms.TextInput(attrs={'class': input_class}),
        'email': forms.EmailInput(attrs={'class': input_class}),
        'website': forms.URLInput(attrs={'class': input_class}),
        'instagram': forms.URLInput(attrs={'class': input_class}),
        'facebook': forms.URLInput(attrs={'class': input_class}),
        'description': forms.Textarea(attrs={'class': 'textarea textarea-bordered w-full bg-white', 'rows': 4}),
    }

class BreweryEditForm(PostalAddressFormMixin, ProcessedImageMixin, forms.ModelForm):
    image_processors = {'image': process_official_image}
    class Meta:
        model = Brewery
        fields = PLACE_EDIT_FIELDS
        widgets = _place_edit_widgets()

class BarEditForm(PostalAddressFormMixin, ProcessedImageMixin, forms.ModelForm):
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

    # Lieu de la brasserie (facultatif) : il distingue deux brasseries de même nom. La ville se déduit du code postal (services/establishments/postal_codes.py).
    brewery_postal_code = forms.CharField(
        required=False, max_length=5, label="Code postal de la brasserie",
        help_text="Facultatif. Utile quand plusieurs brasseries portent ce nom : la ville s'en déduit.",
        widget=forms.TextInput(attrs={
            'inputmode': 'numeric', 'maxlength': 5, 'pattern': r'\d{5}', 'autocomplete': 'off', 'data-postal-group': 'beer', 'data-postal-input': '',
            'data-postal-url': reverse_lazy('postal_code_lookup'), 'placeholder': 'Ex : 44000',
        }),
    )
    brewery_city = forms.CharField(
        required=False, max_length=100, label="Ville",
        widget=forms.TextInput(attrs={'autocomplete': 'off', 'list': 'cities-beer', 'data-postal-group': 'beer', 'data-city-input': ''}),
    )
    # Code-barres lu par le scanner (champ caché, à la création seulement) : validé ici, jamais cru tel quel
    ean = forms.CharField(required=False, widget=forms.HiddenInput())
    # Confirmations : jeton signé envoyé par la case du panneau « doublon probable » (voir services/catalog/catalog_matching.py)
    confirm_brewery = forms.CharField(required=False, max_length=600, widget=forms.HiddenInput())
    confirm_beer = forms.CharField(required=False, max_length=600, widget=forms.HiddenInput())

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
        self.inspection = None  # rapport de détection de doublons, rempli par clean() et affiché par partials/duplicate_panel.html
        self.location = postal_codes.Resolution('', '', False)  # lieu de la brasserie saisie, rempli par clean()
        
        if 'instance' in kwargs and kwargs['instance'] and kwargs['instance'].brewery:
            initial = kwargs.setdefault('initial', {})
            initial['brewery_name'] = kwargs['instance'].brewery.name
            
        super().__init__(*args, **kwargs)
        
        if self.instance.pk:
            del self.fields['ean']  # le code-barres se pose à l'ajout, pas à la modification

        # Le champ image n'est proposé qu'à ceux qui ont le droit de la modifier
        if not self.may_edit_image(self.user, self.instance):
            self.drop_image_field('image')

        for field_name, field in self.fields.items():
            existing_classes = field.widget.attrs.get('class', '')
            # L'image est gérée par le composant partials/image_field.html
            if field_name not in ('image', 'remove_image'):
                field.widget.attrs['class'] = f'{PLAIN_INPUT_CLASS} is-tight placeholder:text-gray-400 {existing_classes}'.strip()

    @staticmethod
    def may_edit_image(user, beer):
        """À la création, l'auteur de la bière peut l'illustrer. Ensuite : le gérant de sa brasserie, ou son créateur tant que
        le staff ne l'a pas vérifiée (la fiche vérifiée est alors garantie par le staff)."""
        if not user:
            return False
        if not beer.pk:
            return True
        if beer.brewery and beer.brewery.managers.filter(id=user.id).exists():
            return True
        return beer.added_by_id == user.id and not beer.is_verified

    def save(self, user=None, commit=True):
        beer = super().save(commit=False)
        b_name = self.cleaned_data['brewery_name']
        # Une brasserie identique (accents, casse, mots génériques) est réutilisée ; sinon elle est créée, après les contrôles de clean()
        report = self.inspection.brewery if self.inspection else catalog_matching.find_brewery(b_name, self.location.postal_code, self.location.city)
        brewery = report.same.obj if report.same else Brewery.objects.create(
            name=b_name, description='Ajoutée automatiquement', postal_code=self.location.postal_code, city=self.location.city,
        )
        beer.brewery = brewery
        if 'ean' in self.fields:  # création seulement : une modification ne touche jamais au code-barres
            beer.ean = self.cleaned_data.get('ean') or None
        
        if user:
            beer.added_by = user
            
        if commit:
            beer.save()
            self.delete_replaced_images()
        return beer
    
    def clean_ean(self):
        """Code valide et pas déjà celui d'une autre bière du catalogue, sinon ignoré (l'ajout de la bière n'est pas bloqué)."""
        code = ean.normalize(self.cleaned_data.get('ean'))
        if code and Beer.objects.filter(ean=code, is_deleted=False).exists():
            return None
        return code

    def clean(self):
        """Détection des doublons (brasserie et bière) : refuse tant que le membre n'a pas choisi l'existant ou confirmé la différence."""
        data = super().clean()
        name, brewery_name = data.get('name'), data.get('brewery_name')
        if not name or not brewery_name:
            return data  # champs déjà en erreur : rien à comparer
        try:
            self.location = postal_codes.resolve(data.get('brewery_postal_code', ''), data.get('brewery_city', ''))
        except postal_codes.PostalCodeError as error:
            self.add_error('brewery_postal_code' if error.field == 'postal_code' else 'brewery_city', str(error))
            return data
        try:
            self.inspection = catalog_matching.decide(
                name, brewery_name, exclude_beer_pk=self.instance.pk,
                confirm_brewery=data.get('confirm_brewery', ''), confirm_beer=data.get('confirm_beer', ''),
                postal_code=self.location.postal_code, city=self.location.city,
            )
        except catalog_matching.DuplicateFound as found:
            self.inspection = found.inspection
            # Erreur non rattachée à un champ : le nom saisi n'est pas vidé, le membre garde de quoi corriger
            raise forms.ValidationError([forms.ValidationError(message, code='duplicate') for message in found.messages]) from None
        return data

    def clean_style(self):
        style = self.cleaned_data.get('style')
        return style_registry.canonicalize(style) if style else style
    
class CustomNotebookForm(forms.ModelForm):
    title = forms.CharField(max_length=150, label="Titre", validators=[plain_text_validator])

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
        fields = ['date', 'note', 'comment', 'photo', 'venue_type', 'company', 'serving_format', 'price']
        labels = {
            'date': 'Date de dégustation',
            'note': 'Note (sur 10)',
            'comment': 'Mon avis personnel'
        }
        widgets = {
            'date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'comment': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Votre expérience, vos impressions en toute subjectivité...', 'class': 'textarea textarea-bordered w-full'}),
            'note': forms.NumberInput(attrs={'min': 0, 'max': 10}),
            'venue_type': forms.RadioSelect,
            'company': forms.RadioSelect,
            'serving_format': forms.RadioSelect,
            'price': forms.NumberInput(attrs={'min': 0, 'max': 999, 'step': '0.10', 'inputmode': 'decimal', 'placeholder': 'Prix en €'}),
        }

    CHOICE_FIELDS = ('venue_type', 'company', 'serving_format')  # boutons à choix unique, affichés par le gabarit

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields['note'].required = False
        for name in self.CHOICE_FIELDS:
            self.fields[name].required = False
            self.fields[name].choices = [choice for choice in self.fields[name].choices if choice[0] != '']  # pas de choix vide : on ne coche rien
        for name, field in self.fields.items():
            if name in ('photo', 'remove_photo') or name in self.CHOICE_FIELDS:
                continue  # gérés par le composant partials/image_field.html ou par des boutons de choix
            field.widget.attrs.update({'class': 'pb-input placeholder:text-gray-400'})

    def clean_date(self):
        date = self.cleaned_data['date']
        if not self.instance.pk or date != self.instance.date:  # une date déjà enregistrée n'est pas revalidée à chaque modification
            validate_tasting_date(date)
        return date

    def _post_clean(self):
        super()._post_clean()
        # Le quota n'est consommé qu'une fois tout le formulaire valide : une erreur de saisie ne fait pas perdre d'envoi
        if not self.errors and self.user and self.uploaded_image('photo') and not consume_quota(self.user, DAILY_LIMIT, QUOTA_SCOPE):
            self.add_error('photo', ValidationError("Limite quotidienne d'envois de photos atteinte, réessayez demain.", code='quota'))

class MenuEntryForm(forms.ModelForm):
    """Prix de vente et format d'une bière de la carte d'un bar : tous deux facultatifs."""

    class Meta:
        model = BarBeer
        fields = ['price', 'serving_format']
        widgets = {
            'price': forms.NumberInput(attrs={'min': 0, 'max': 999, 'step': '0.10', 'inputmode': 'decimal', 'placeholder': 'Prix en €'}),
            'serving_format': forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['price'].required = False
        self.fields['serving_format'].required = False
        # Pas de choix vide : on ne coche rien (comme le formulaire d'une dégustation)
        self.fields['serving_format'].choices = [choice for choice in self.fields['serving_format'].choices if choice[0] != '']
        self.fields['price'].widget.attrs['class'] = f'{PLAIN_INPUT_CLASS} is-tight placeholder:text-gray-400'


class FeedbackForm(forms.Form):
    """Premier message d'un échange avec l'équipe."""
    message = forms.CharField(
        max_length=MAX_FEEDBACK_LENGTH, label="Votre suggestion, remarque ou bug",
        widget=forms.Textarea(attrs={
            'rows': 4, 'maxlength': MAX_FEEDBACK_LENGTH, 'class': PLAIN_INPUT_CLASS,
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


class MarketingConsentForm(forms.Form):
    """Choix des e-mails promotionnels (page du compte) : le choix est horodaté et son origine conservée.

    Formulaire simple et non ModelForm : un ModelForm modifierait l'instance avant l'enregistrement, et le service ne verrait plus le changement.
    """
    marketing_opt_in = forms.BooleanField(
        required=False, label="Recevoir les nouveautés par e-mail",
        widget=forms.CheckboxInput(attrs={'class': 'toggle toggle-sm toggle-primary'}),
    )

    def __init__(self, *args, user, source=marketing.ACCOUNT, **kwargs):
        self.user, self.source = user, source
        super().__init__(*args, initial={'marketing_opt_in': user.marketing_opt_in}, **kwargs)

    def save(self):
        return marketing.set_consent(self.user, self.cleaned_data['marketing_opt_in'], self.source)


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
        elif target == self.reporter or (item_type == 'drink' and target.drinker_id == self.reporter.pk):
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
