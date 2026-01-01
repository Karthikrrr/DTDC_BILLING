from django.db import models


class Company(models.Model):
    name = models.CharField(max_length=255, unique=True)
    rule_file = models.FileField(upload_to="company_rules/")
    active = models.BooleanField(default=True)
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
    docket_no = models.CharField(max_length=50)
    date = models.DateField()
    destination = models.CharField(max_length=255)
    pincode = models.CharField(max_length=10)
    segment = models.CharField(max_length=50, blank=True, null=True)
    pieces = models.IntegerField(default=0)
    weight = models.FloatField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    month = models.CharField(max_length=7)

    class Meta:
        unique_together = (("company", "docket_no", "month"),)

    def __str__(self):
        return f"{self.company.name} - {self.docket_no}"
