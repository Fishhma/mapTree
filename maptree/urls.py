from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "mapTree — редактирование"
admin.site.site_title = "mapTree"
admin.site.index_title = "Данные древа"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("genealogy.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
