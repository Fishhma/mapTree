"""Вход, выход и регистрация по приглашению.

Приглашение — одноразовая ссылка /invite/<код>/, которую администратор создаёт в
админке и отправляет человеку. По ней можно один раз зарегистрироваться; после
регистрации у человека появляется своё пустое древо. Без приглашения
зарегистрироваться нельзя.
"""
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone

from .models import FamilyTree, Invitation


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
