from django.db import models

class Company(models.Model):
    name = models.CharField(max_length=255, unique=True)
    rule_file = models.FileField(upload_to="company_rules/")
    address = models.CharField(max_length=300, null=True, default="Mysore karnataka")
    gst_no = models.CharField(max_length=50, null=True, default="00000000000")
    active = models.BooleanField(default=True)
    fsc_percent = models.IntegerField(null=True, default=40)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Invoice(models.Model):
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class PincodeFile(models.Model):
    file = models.FileField(upload_to="pincode/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Pincode File ({self.uploaded_at.date()})"


class Bill(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="bills"
    )
    docket_no = models.CharField(max_length=50)
    date = models.DateField()
    destination = models.CharField(max_length=255)
    mode = models.CharField(max_length=100, null=True, default="NONE")
    fsc_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )
    inv_amount = models.FloatField(null=True,default=0)
    inv_amt_percent = models.FloatField(null=True, default=0)
    oda_charges = models.FloatField(null=True, default=0)
    pincode = models.CharField(max_length=10)
    segment = models.CharField(max_length=50, blank=True, null=True)
    pieces = models.IntegerField(default=0)
    manifest_weight = models.FloatField(null=True)
    vol_weight = models.FloatField(null=True)
    weight = models.FloatField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    month = models.CharField(max_length=7)
    doc_type = models.CharField(max_length=10, default="NONE")

    class Meta:
        unique_together = (("company", "docket_no", "month"),)

    def __str__(self):
        return f"{self.company.name} - {self.docket_no}"


class FinalDetails(models.Model):
    company_name = models.CharField(max_length=30)
    inv_date = models.DateTimeField(auto_now_add=False)
    inv_number = models.CharField(max_length=20)
    sgst = models.FloatField(default=0)
    cgst = models.FloatField(default=0)
    igst = models.FloatField(default=0)
    grand_total = models.FloatField(default=0)

