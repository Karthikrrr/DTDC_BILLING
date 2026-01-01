from django.db import models

class ManifestUpload(models.Model):
    file = models.FileField(upload_to='manifest/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Manifest {self.id}"

class ManifestRecord(models.Model):
    manifest = models.ForeignKey(ManifestUpload, on_delete=models.CASCADE)
    docket_no = models.CharField(max_length=50, db_index=True)
    manifest_date = models.DateField(null=True, blank=True)
    pincode = models.CharField(max_length=100, null=True)
    pieces = models.CharField(max_length=100, null=True)

    def __str__(self):
        return self.docket_no

class ScannedDocket(models.Model):
    company_name = models.CharField(max_length=255)
    docket_no = models.CharField(max_length=50, db_index=True)
    scanned_at = models.DateTimeField(auto_now_add=True)
    pincode = models.CharField(max_length=100, null=True)
    pieces = models.CharField(max_length=100, null=True)
    matched = models.BooleanField(default=False)
    manifest_date = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = ("company_name", "docket_no")

    def __str__(self):
        return f"{self.company_name} - {self.docket_no}"

