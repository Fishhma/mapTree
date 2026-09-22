from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Person(models.Model):
    class Sex(models.TextChoices):
        FEMALE = "F", "Female"
        MALE = "M", "Male"
        UNSPECIFIED = "U", "Unspecified"

    given_name = models.CharField(max_length=80)
    family_name = models.CharField(max_length=80)
    birth_date = models.DateField(null=True, blank=True)
    death_date = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=1, choices=Sex.choices, default=Sex.UNSPECIFIED)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["birth_date", "family_name", "given_name"]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f"{self.given_name} {self.family_name}".strip()


class Partnership(models.Model):
    partner_a = models.ForeignKey(
        Person, on_delete=models.CASCADE, related_name="partnerships_as_a"
    )
    partner_b = models.ForeignKey(
        Person, on_delete=models.CASCADE, related_name="partnerships_as_b"
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    label = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["start_date", "id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(partner_a=models.F("partner_b")),
                name="partnership_partners_differ",
            ),
            models.UniqueConstraint(
                fields=["partner_a", "partner_b"],
                name="unique_ordered_partnership",
            ),
        ]

    def __str__(self):
        return self.label or f"{self.partner_a} + {self.partner_b}"

    @property
    def partners(self):
        return (self.partner_a, self.partner_b)


class ParentChild(models.Model):
    parent = models.ForeignKey(
        Person, on_delete=models.CASCADE, related_name="children_links"
    )
    child = models.ForeignKey(
        Person, on_delete=models.CASCADE, related_name="parent_links"
    )
    partnership = models.ForeignKey(
        Partnership,
        on_delete=models.SET_NULL,
        related_name="parent_child_links",
        null=True,
        blank=True,
    )
    birth_order = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(99)]
    )

    class Meta:
        ordering = ["child__birth_date", "birth_order", "parent_id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(parent=models.F("child")),
                name="parent_child_people_differ",
            ),
            models.UniqueConstraint(
                fields=["parent", "child"],
                name="unique_parent_child_link",
            ),
        ]

    def __str__(self):
        return f"{self.parent} → {self.child}"
