from django.shortcuts import render, redirect
from django.http import HttpResponse
from .models import ManifestUpload, ManifestRecord, ScannedDocket
from django.utils.timezone import localtime
from .utils import process_manifest
import pandas as pd
from billing.models import Company
from django.db import IntegrityError

def upload_manifest(request):
    error = None

    if request.method == 'POST':
        file = request.FILES['file']
        manifest = ManifestUpload.objects.create(file=file)

        try:
            process_manifest(file, manifest)
            return redirect('scan_docket')
        except Exception as e:
            manifest.delete()
            error = str(e)

    return render(request, 'upload_manifest.html', {'error': error})


def scan_docket(request):
    message = None
    error = None
    companies = Company.objects.filter(active=True)

    if request.method == 'POST':
        company_name = request.POST.get('company')
        dockets_text = request.POST.get('docket_numbers', '')

        if not company_name:
            error = "Please select a company."
        elif not dockets_text.strip():
            error = "Please scan or enter at least one docket number."
        else:
            dockets = [
                d.strip()
                for d in dockets_text.splitlines()
                if d.strip()
            ]

            saved = 0
            matched = 0
            skipped = 0

            for docket in dockets:
                record = ManifestRecord.objects.filter(
                    docket_no=docket
                ).first()

                pincode = record.pincode if record else None
                pieces = record.pieces if record else None

                if ScannedDocket.objects.filter(
                    company_name=company_name,
                    docket_no=docket
                ).exists():
                    skipped += 1
                    continue

                try:
                    ScannedDocket.objects.create(
                        company_name=company_name,
                        docket_no=docket,
                        matched=bool(record),
                        manifest_date=record.manifest_date if record else None,
                        pincode=pincode,
                        pieces=pieces
                    )
                    saved += 1
                    if record:
                        matched += 1

                except IntegrityError:
                    skipped += 1

            message = (
                f"Saved: {saved} | "
                f"Matched: {matched} | "
                f"Duplicates skipped: {skipped}"
            )

    return render(request, 'scan_docket.html', {
        'companies': companies,
        'message': message,
        'error': error
    })


def missing_dockets(request):
    scanned = ScannedDocket.objects.values_list('docket_no', flat=True)
    missing = ManifestRecord.objects.exclude(docket_no__in=scanned)

    return render(request, 'missing_dockets.html', {
        'missing': missing
    })

def download_missing_excel(request):
    # Dockets scanned (all companies)
    scanned_dockets = ScannedDocket.objects.values_list(
        'docket_no', flat=True
    )

    missing = ManifestRecord.objects.exclude(
        docket_no__in=scanned_dockets
    )

    data = []
    for m in missing:
        data.append({
            "Docket No": m.docket_no,
            "Booking Date": m.manifest_date,
            "GetData": ""   # empty column as requested
        })

    df = pd.DataFrame(data)

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = (
        'attachment; filename="missing_dockets.xlsx"'
    )

    df.to_excel(response, index=False)
    return response

def download_excel(request):
    scanned = ScannedDocket.objects.filter(matched=True)

    data = []
    for s in scanned:
        data.append({
            "Company Name": s.company_name,
            "Docket No": s.docket_no,
            "Booking Date": s.manifest_date,
            "Pin Code":s.pincode,
            "No.of Pieces":s.pieces
        })

    df = pd.DataFrame(data)

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="final.xlsx"'

    df.to_excel(response, index=False)
    return response

def merge_excel(request):
    message = None

    if request.method == 'POST':
        file1 = request.FILES.get('excel1')
        file2 = request.FILES.get('excel2')

        if not file1 or not file2:
            message = "Please upload both Excel files."
        else:
            try:
                import pandas as pd
                from django.http import HttpResponse

                # Read Excel files
                df1 = pd.read_excel(file1)
                df2 = pd.read_excel(file2)

                # ----- VALIDATE REQUIRED COLUMNS -----
                excel1_required = [
                    "Company Name",
                    "Docket No",
                    "Booking Date",
                    "Pin Code",
                    "No.of Pieces"
                ]

                excel2_required = [
                    "CnNo",
                    "Weight",
                    "Mode",
                    "Destination City",
                    "Document Type"
                ]

                for col in excel1_required:
                    if col not in df1.columns:
                        raise ValueError(f"Excel 1 missing column: {col}")

                for col in excel2_required:
                    if col not in df2.columns:
                        raise ValueError(f"Excel 2 missing column: {col}")

                # ----- PREPARE JOIN KEYS -----
                df1["_JOIN_KEY_"] = df1["Docket No"].astype(str).str.strip()
                df2["_JOIN_KEY_"] = df2["CnNo"].astype(str).str.strip()

                # ----- SELECT ONLY REQUIRED COLUMNS -----
                df1_clean = df1[
                    ["Company Name", "Docket No", "Booking Date", "Pin Code", "No.of Pieces", "_JOIN_KEY_"]
                ]

                df2_clean = df2[
                    ["_JOIN_KEY_", "Weight", "Mode", "Destination City", "Document Type"]
                ]

                # ----- MERGE (LEFT JOIN) -----
                merged_df = pd.merge(
                    df1_clean,
                    df2_clean,
                    on="_JOIN_KEY_",
                    how="left"
                )

                # ----- DROP JOIN KEY -----
                merged_df.drop(columns=["_JOIN_KEY_"], inplace=True)

                # ----- ENSURE COLUMN ORDER -----
                merged_df = merged_df[
                    [
                        "Company Name",
                        "Docket No",
                        "Booking Date",
                        "Pin Code",
                        "No.of Pieces",
                        "Weight",
                        "Mode",
                        "Destination City",
                        "Document Type"
                    ]
                ]

                # ----- DOWNLOAD EXCEL -----
                response = HttpResponse(
                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                response["Content-Disposition"] = 'attachment; filename="merged_excel.xlsx"'

                merged_df.to_excel(response, index=False)
                return response

            except Exception as e:
                message = f"Merge failed: {str(e)}"

    return render(request, 'merge_excel.html', {
        'message': message
    })
