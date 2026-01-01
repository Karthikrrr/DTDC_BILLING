from django.contrib import admin

from manifest.models import ManifestRecord, ManifestUpload, ScannedDocket

# Register your models here.
@admin.register(ManifestUpload)
class ManifestUploadAdmin(admin.ModelAdmin):
    list_display = ("id", "file", "uploaded_at")
    search_fields = ("file",)
    ordering = ("-uploaded_at",)

@admin.register(ManifestRecord)
class ManifestRecordAdmin(admin.ModelAdmin):
    list_display = ("docket_no", "manifest_date", "manifest")
    search_fields = ("docket_no",)
    list_filter = ("manifest_date",)

@admin.register(ScannedDocket)
class ScannedDocketAdmin(admin.ModelAdmin):
    list_display = (
        "company_name",
        "docket_no",
        "matched",
        "manifest_date",
        "scanned_at",
    )
    list_filter = ("matched", "company_name")
    search_fields = ("docket_no", "company_name")
    ordering = ("-scanned_at",)
