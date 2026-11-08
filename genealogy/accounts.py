"""Вход, выход, регистрация по приглашению и страница «Аккаунт».

Приглашение — одноразовая ссылка /invite/<код>/, которую администратор создаёт в
админке и отправляет человеку. По ней можно один раз зарегистрироваться; после
регистрации у человека появляется своё пустое древо. Без приглашения
зарегистрироваться нельзя.

Страница /account/: смена логина и пароля, «удалить древо и начать заново»
(после этого снова открывается окно первого входа — можно загрузить GEDCOM)
и удаление учётной записи вместе с древом. Удаление защищено от случайного
нажатия: нужно ввести свой пароль и вписать подтверждение.
"""
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from .importer import clear_tree
from .models import FamilyTree, Invitation, Source

User = get_user_model()
CLEAR_PHRASE = "удалить древо"


class RegisterForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        fields = ("username",)
        labels = {"username": "Логин"}


@login_not_required
def register(request, code):
    invitation = Invitation.objects.filter(code=code).first()
    if invitation is None or not invitation.is_usable:
        return render(request, "registration/invite_invalid.html", {"invitation": invitation}, status=404)
    if request.user.is_authenticated:
        return render(request, "registration/invite_invalid.html",
                      {"invitation": invitation, "signed_in": True}, status=400)
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)
            if not invitation.is_usable:          # пока заполняли форму, ссылку уже использовали
                return render(request, "registration/invite_invalid.html", {"invitation": invitation},
                              status=404)
            user = form.save()
            FamilyTree.objects.create(owner=user)
            invitation.used_by, invitation.used_at = user, timezone.now()
            invitation.save(update_fields=["used_by", "used_at"])
        login(request, user)
        return redirect("tree")
    return render(request, "registration/register.html", {"form": form, "invitation": invitation})


# ---------- страница «Аккаунт» ----------

def _password_field(label="Ваш пароль"):
    return forms.CharField(label=label, strip=False,
                           widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class UsernameForm(forms.ModelForm):
    """Новый логин. Нынешний пароль — чтобы логин не сменил тот, кто сел за чужой компьютер."""
    password = _password_field()

    class Meta:
        model = User
        fields = ("username",)
        labels = {"username": "Новый логин"}
        help_texts = {"username": ""}

    def __init__(self, user, *args, **kwargs):
        # Отдельная копия: форма меняет свой объект ещё до проверки, а шапка страницы
        # должна показывать нынешний логин, пока новый не сохранён.
        super().__init__(*args, instance=User.objects.get(pk=user.pk), **kwargs)
        self.old_username = user.username

    def clean_username(self):
        username = self.cleaned_data["username"]
        if username == self.old_username:
            raise forms.ValidationError("Это и есть ваш нынешний логин.")
        return username

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.instance.check_password(password):
            raise forms.ValidationError("Неверный пароль.")
        return password


class ConfirmForm(forms.Form):
    """Подтверждение опасного действия: свой пароль и вписанная фраза."""
    password = _password_field()
    confirm = forms.CharField(label="Подтверждение", widget=forms.TextInput(attrs={"autocomplete": "off"}))

    def __init__(self, user, phrase: str, *args, exact=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.user, self.phrase, self.exact = user, phrase, exact
        self.fields["confirm"].label = f"Впишите «{phrase}»"

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("Неверный пароль.")
        return password

    def clean_confirm(self):
        typed = self.cleaned_data["confirm"].strip()
        same = (typed == self.phrase if self.exact
                else " ".join(typed.split()).casefold() == self.phrase.casefold())
        if not same:
            raise forms.ValidationError(f"Нужно вписать «{self.phrase}».")
        return typed


def can_delete_account(user) -> bool:
    """Последнего администратора удалить нельзя: иначе некому будет войти в админку."""
    if not user.is_superuser:
        return True
    return User.objects.filter(is_superuser=True, is_active=True).exclude(pk=user.pk).exists()


def account(request):
    user = request.user
    tree = FamilyTree.of(user)
    action = request.POST.get("action") if request.method == "POST" else None

    def data(name):
        return request.POST if action == name else None

    # auto_id: у полей разных форм на одной странице должны быть разные id.
    username_form = UsernameForm(user, data("username"), auto_id="login_%s")
    password_form = PasswordChangeForm(user, data("password"), auto_id="password_%s")
    password_form.fields["old_password"].widget.attrs.pop("autofocus", None)
    password_form.fields["new_password2"].help_text = ""
    clear_form = ConfirmForm(user, CLEAR_PHRASE, data("clear"), auto_id="clear_%s")
    delete_form = ConfirmForm(user, user.username, data("delete"), exact=True, auto_id="delete_%s")
    deletable = can_delete_account(user)

    if action == "username" and username_form.is_valid():
        username_form.save()
        messages.success(request, f"Логин изменён. Теперь вы входите как «{username_form.instance.username}».",
                         extra_tags="login")
        return redirect(reverse("account") + "#login")
    if action == "password" and password_form.is_valid():
        password_form.save()
        update_session_auth_hash(request, password_form.user)   # чтобы не выкинуло со страницы
        messages.success(request, "Пароль изменён.", extra_tags="password")
        return redirect(reverse("account") + "#password")
    if action == "clear" and clear_form.is_valid():
        with transaction.atomic():
            clear_tree(tree)
        return redirect("tree")                                  # там откроется окно первого входа
    if action == "delete" and deletable and delete_form.is_valid():
        logout(request)
        with transaction.atomic():
            user.delete()                                        # древо, люди и материалы — следом
        return render(request, "registration/account_deleted.html")

    return render(request, "genealogy/account.html", {
        "tree": tree,
        "people": tree.people.count(),
        "materials": Source.objects.filter(tree=tree).count(),
        "username_form": username_form,
        "password_form": password_form,
        "clear_form": clear_form,
        "delete_form": delete_form,
        "deletable": deletable,
        "clear_phrase": CLEAR_PHRASE,
        "danger_open": action in ("clear", "delete"),
    }, status=400 if action else 200)
