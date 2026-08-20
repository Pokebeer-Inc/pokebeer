from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import BeerUser, Beer, Brewery, Drinks, Feedback, Bar, Report
from django.utils.text import slugify

from unfold.contrib.forms.widgets import ArrayWidget, WysiwygWidget

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
        fields = ['name', 'brewery_name', 'style', 'description', 'bitterness', 'degree']
        labels = {
            'name': 'Nom de la bière',
            'description': 'Description officielle (Optionnel)',
            'bitterness': 'IBU (Optionnel)',
            'degree': 'Alcool (%)',
            'style': 'Style de bière (Optionnel)',
        }
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Historique, arômes selon le brasseur...'}),
            'name': forms.TextInput(attrs={'autocomplete': 'off', 'placeholder': 'Ex: Punk IPA'})
        }

    def __init__(self, *args, **kwargs):
        # Pré-remplir le champ 'brewery_name' si on est en mode édition (instance existante)
        if 'instance' in kwargs and kwargs['instance'] and kwargs['instance'].brewery_id:
            initial = kwargs.setdefault('initial', {})
            initial['brewery_name'] = kwargs['instance'].brewery_id.name
            
        super(BeerForm, self).__init__(*args, **kwargs)
        
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get('class', '')
            
            field.widget.attrs.update({
                'class': f'form-control placeholder:text-gray-400 {existing_classes}'.strip(),
                'style': 'width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box;'
            })

    def save(self, user=None, commit=True):
        beer = super(BeerForm, self).save(commit=False)
        b_name = self.cleaned_data['brewery_name']
        brewery, created = Brewery.objects.get_or_create(
            name__iexact=b_name,
            defaults={'name': b_name, 'city': 'Inconnue', 'description': 'Ajoutée automatiquement'}
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
            # On ignore les bières supprimées dans la vérification des doublons
            existing_beer = Beer.objects.filter(slug=normalized_name, is_deleted=False).first()
            if existing_beer:
                # Si on est en mode modification et que c'est notre propre bière, on laisse passer
                if self.instance and self.instance.pk == existing_beer.pk:
                    pass
                else:
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