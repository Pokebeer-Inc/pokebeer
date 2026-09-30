from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.core.exceptions import ValidationError
from .models import BeerUser, Beer, Brewery, CustomNotebook, Drinks, Feedback, Bar, Report
from django.utils import timezone
from django.utils.text import slugify

from unfold.contrib.forms.widgets import ArrayWidget, WysiwygWidget

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

class UserRegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = BeerUser
        # Fields you want the user to fill in
        fields = ['username', 'email']

    def clean_email(self):
        # Add custom validation to ensure email is unique
        email = self.cleaned_data.get('email')
        if BeerUser.objects.filter(email=email).exists():
            raise forms.ValidationError("Cet email est déjà utilisé.")
        return email
    
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

class UserLoginForm(AuthenticationForm):
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

    def __init__(self, *args, **kwargs):
        super(UserLoginForm, self).__init__(*args, **kwargs)
        
        # On définit explicitement les labels
        self.fields['username'].label = "Pseudo"
        self.fields['password'].label = "Mot de passe"
        
        # On applique les classes visuelles et le placeholder
        for field_name, field in self.fields.items():
            
            field.widget.attrs.update({
                'class': 'input input-bordered w-full bg-white/80 focus:bg-white transition-colors'
            })

class UserUpdateForm(forms.ModelForm):
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

    def clean_email(self):
        email = self.cleaned_data.get('email')
        # On vérifie si l'email existe déjà chez un AUTRE utilisateur (exclure self.instance)
        if BeerUser.objects.filter(email=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Cet email est déjà utilisé par un autre membre.")
        return email

class ProSettingsForm(forms.ModelForm):
    show_establishments = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'toggle toggle-primary toggle-sm'})
    )

    class Meta:
        model = BeerUser
        fields = ['show_establishments']
    
class ProUserForm(forms.ModelForm):
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

class BarProForm(forms.ModelForm):
    siret = forms.CharField(max_length=14, min_length=14, required=True, label="Numéro SIRET (14 chiffres)", widget=forms.TextInput(attrs={'class': 'input input-bordered w-full bg-white', 'placeholder': 'Ex: 12345678901234'}))
    
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

class BreweryProForm(forms.ModelForm):
    siret = forms.CharField(max_length=14, min_length=14, required=True, label="Numéro SIRET (14 chiffres)", widget=forms.TextInput(attrs={'class': 'input input-bordered w-full bg-white', 'placeholder': 'Ex: 12345678901234'}))
    
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
            
class BreweryEditForm(forms.ModelForm):
    class Meta:
        model = Brewery
        fields = ['name', 'description', 'address', 'phone', 'email', 'website', 'instagram', 'facebook', 'image']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input input-bordered w-full bg-white'}),
            'address': forms.TextInput(attrs={'class': 'input input-bordered w-full bg-white'}),
            'phone': forms.TextInput(attrs={'class': 'input input-bordered w-full bg-white'}),
            'email': forms.EmailInput(attrs={'class': 'input input-bordered w-full bg-white'}),
            'website': forms.URLInput(attrs={'class': 'input input-bordered w-full bg-white'}),
            'instagram': forms.URLInput(attrs={'class': 'input input-bordered w-full bg-white'}),
            'facebook': forms.URLInput(attrs={'class': 'input input-bordered w-full bg-white'}),
            'description': forms.Textarea(attrs={'class': 'textarea textarea-bordered w-full bg-white', 'rows': 4}),
            'image': forms.ClearableFileInput(attrs={'class': 'file-input file-input-bordered file-input-primary w-full bg-white text-gray-700 mt-2'}),
}

class BeerForm(forms.ModelForm):
    brewery_name = forms.CharField(
        label='Brasserie',
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
            'image': 'Image officielle (Gérants uniquement)',
        }
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Historique, arômes selon le brasseur...'}),
            'name': forms.TextInput(attrs={'autocomplete': 'off', 'placeholder': 'Ex: Punk IPA'}),
            'image': forms.ClearableFileInput(attrs={'class': 'file-input file-input-bordered file-input-primary w-full bg-white text-gray-700'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        
        if 'instance' in kwargs and kwargs['instance'] and kwargs['instance'].brewery_id:
            initial = kwargs.setdefault('initial', {})
            initial['brewery_name'] = kwargs['instance'].brewery_id.name
            
        super(BeerForm, self).__init__(*args, **kwargs)
        
        # On masque le champ image si l'utilisateur n'a pas les droits
        if self.user:
            if self.instance and self.instance.pk and self.instance.brewery_id:
                # En édition : on vérifie s'il gère CETTE brasserie spécifique
                if not self.instance.brewery_id.managers.filter(id=self.user.id).exists():
                    self.fields.pop('image', None)
            else:
                # En création : s'il ne gère AUCUNE brasserie, inutile d'afficher le champ
                if not self.user.my_breweries.exists():
                    self.fields.pop('image', None)
        else:
            self.fields.pop('image', None)
        
        for field_name, field in self.fields.items():
            existing_classes = field.widget.attrs.get('class', '')
            # On ne surcharge pas le style de l'input fichier
            if field_name != 'image':
                field.widget.attrs.update({
                    'class': f'form-control placeholder:text-gray-400 {existing_classes}'.strip(),
                    'style': 'width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box;'
                })

    def clean(self):
        """Vérification de sécurité finale anti-fraude sur l'image"""
        cleaned_data = super().clean()
        image = cleaned_data.get('image')
        b_name = cleaned_data.get('brewery_name')
        
        # Si une image est envoyée, on vérifie strictement que l'utilisateur gère la brasserie TAPPÉE
        if image and b_name and self.user:
            brewery = Brewery.objects.filter(name__iexact=b_name).first()
            if not brewery or not brewery.managers.filter(id=self.user.id).exists():
                self.add_error('image', "Action refusée : Vous devez être le gérant de cette brasserie pour uploader une image officielle.")
        return cleaned_data

    def save(self, user=None, commit=True):
        beer = super(BeerForm, self).save(commit=False)
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
    spot_id = forms.IntegerField(required=False, min_value=1, label="Lieu")
    title = forms.CharField(max_length=150, label="Titre")
    description = forms.CharField(required=False, label="Description")
    date = forms.DateField(required=False, label="Date")
    # FloatField refuse aussi NaN et l'infini
    lat = forms.FloatField(min_value=-90, max_value=90, label="Latitude")
    lng = forms.FloatField(min_value=-180, max_value=180, label="Longitude")

class DrinkForm(forms.ModelForm):
    class Meta:
        model = Drinks
        fields = ['date', 'note', 'comment']
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

    def __init__(self, *args, **kwargs):
        super(DrinkForm, self).__init__(*args, **kwargs)
        self.fields['note'].required = False
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'form-control placeholder:text-gray-400',
                'style': 'width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; margin-bottom: 10px;'
            })
            
class FeedbackForm(forms.ModelForm):
    class Meta:
        model = Feedback
        fields = ['message']
        labels = {
            'message': "Votre suggestion, remarque ou bug"
        }
        widgets = {
            'message': forms.Textarea(attrs={'rows': 4})
        }

    def __init__(self, *args, **kwargs):
        super(FeedbackForm, self).__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'form-control',
                'style': 'width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; margin-bottom: 10px;'
            })
            
class NotificationPreferenceForm(forms.ModelForm):
    class Meta:
        model = BeerUser
        fields = ['notif_global', 'notif_follow', 'notif_social', 'notif_network', 'notif_achievements']
        widgets = {
            'notif_global': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary'}),
            'notif_follow': forms.CheckboxInput(attrs={'class': 'toggle toggle-sm toggle-primary'}),
            'notif_social': forms.CheckboxInput(attrs={'class': 'toggle toggle-sm toggle-primary'}),
            'notif_network': forms.CheckboxInput(attrs={'class': 'toggle toggle-sm toggle-primary'}),
            'notif_achievements': forms.CheckboxInput(attrs={'class': 'toggle toggle-sm toggle-primary'}),
        }


class ReportForm(forms.Form):
    """Signalement envoyé depuis les modales (bière, avis, profil, brasserie)."""
    TARGET_MODELS = {'beer': Beer, 'drink': Drinks, 'user': BeerUser, 'brewery': Brewery}
    DESCRIPTION_MIN_LENGTH = 10
    DESCRIPTION_MAX_LENGTH = 1000

    item_type = forms.ChoiceField(choices=[(key, key) for key in TARGET_MODELS], label="Élément signalé")
    item_id = forms.IntegerField(min_value=1, label="Élément signalé")
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

        item_type, item_id = cleaned_data.get('item_type'), cleaned_data.get('item_id')
        if not (item_type and item_id):
            return cleaned_data

        target = self.TARGET_MODELS[item_type].objects.filter(pk=item_id).first()
        if target is None:
            self.add_error('item_id', "L'élément signalé n'existe pas ou plus.")
        elif target == self.reporter or (item_type == 'drink' and target.drinker_id_id == self.reporter.pk):
            self.add_error('item_id', "Vous ne pouvez pas signaler votre propre profil ou votre propre avis.")
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
            "admin_response": WysiwygWidget,
        }
        

class FeedbackAdminForm(forms.ModelForm):
    class Meta:
        model = Feedback
        fields = (
            "status",
            "admin_reply",
        )

        widgets = {
            "admin_response": WysiwygWidget,
        }