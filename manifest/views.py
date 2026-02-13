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
    pieces_count = 1   # default for UI

    if request.method == 'POST':
        company_name = request.POST.get('company')
        dockets_text = request.POST.get('docket_numbers', '')
        lbh_json = request.POST.get('lbh_json')

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
            skipped = 0

            for docket in dockets:
                record = ManifestRecord.objects.filter(docket_no=docket).first()

                # ❌ If docket not found in manifest
                if not record:
                    skipped += 1
                    continue

                # ✅ Pieces from manifest (DSR_NO_OF_PIECES)
                try:
                    pieces_count = int(record.pieces)
                except (TypeError, ValueError):
                    pieces_count = 1

                # ✅ If LBH JSON missing → default LBH = 0 per piece
                if not lbh_json:
                    default_lbh = []
                    for i in range(1, pieces_count + 1):
                        default_lbh.append({
                            "piece": i,
                            "l": 0,
                            "b": 0,
                            "h": 0
                        })
                    lbh_json_to_store = default_lbh
                else:
                    lbh_json_to_store = lbh_json

                # ✅ Overwrite allowed
                ScannedDocket.objects.update_or_create(
                    company_name=company_name,
                    docket_no=docket,
                    defaults={
                        "matched": True,
                        "manifest_date": record.manifest_date,
                        "pincode": record.pincode,
                        "pieces": record.pieces,
                        "lbh_data": lbh_json_to_store,
                        "manifest_weight": getattr(record, "DSR_CN_WEIGHT", 0),
                        "mode": getattr(record, "MODE", None),
                    }
                )

                saved += 1

            message = (
                f"Saved / Updated: {saved} dockets. "
                f"Skipped (not in manifest): {skipped}"
            )

    return render(request, 'scan_docket.html', {
        'companies': companies,
        'message': message,
        'error': error,
        'pieces_count': pieces_count
    })


from django.http import JsonResponse

def get_pieces_by_docket(request):
    docket = request.GET.get("docket")

    record = ManifestRecord.objects.filter(docket_no=docket).first()

    if record and record.pieces:
        try:
            pieces = int(record.pieces)
        except ValueError:
            pieces = 1
    else:
        pieces = 1

    return JsonResponse({"pieces": pieces})




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
                import json
                import pandas as pd
                from django.http import HttpResponse

                # ---------- Helper: Parse LBH safely ----------
                def parse_lbh_data(lbh):
                    if not lbh:
                        return []
                    if isinstance(lbh, list):
                        return lbh
                    try:
                        return json.loads(lbh)
                    except Exception:
                        return []

                # ---------- Helper: Calculate Volumetric Weight ----------
                def calculate_vol_weight(lbh_list, mode):
                    total = 0.0

                    for item in lbh_list:
                        l = float(item.get("l", 0))
                        b = float(item.get("b", 0))
                        h = float(item.get("h", 0))

                        if l == 0 or b == 0 or h == 0:
                            continue

                        if mode == "SURFACE":
                            total += (l * b * h) * (9 / 27000)
                        else:
                            total += (l * b * h) / 5000

                    return round(total, 2)

                # ---------- Read Excel files ----------
                df1 = pd.read_excel(file1)
                df2 = pd.read_excel(file2)

                # ---------- Prepare join keys ----------
                df1["_JOIN_KEY_"] = df1["Docket No"].astype(str).str.strip()
                df2["_JOIN_KEY_"] = df2["CnNo"].astype(str).str.strip()

                # ---------- Select required columns ----------
                df1_clean = df1[
                    ["Company Name", "Docket No", "Booking Date", "Pin Code", "No.of Pieces", "_JOIN_KEY_"]
                ]

                df2_clean = df2[
                    ["_JOIN_KEY_", "Weight", "Mode", "Destination City", "Document Type"]
                ]

                # ---------- Merge ----------
                merged_df = pd.merge(
                    df1_clean,
                    df2_clean,
                    on="_JOIN_KEY_",
                    how="left"
                )

                merged_df.drop(columns=["_JOIN_KEY_"], inplace=True)

                # ---------- Calculate Weights ----------
                vol_weights = []
                final_weights = []

                for _, row in merged_df.iterrows():
                    docket = row["Docket No"]

                    # Delivery weight from Excel-2
                    delivery_weight = (
                        float(row["Weight"]) if not pd.isna(row["Weight"]) else 0.0
                    )

                    # Mode from Excel-2
                    mode = str(row["Mode"]).strip().upper() if not pd.isna(row["Mode"]) else ""

                    vol_weight = 0.0

                    scanned = ScannedDocket.objects.filter(
                        docket_no=docket
                    ).first()

                    if scanned and scanned.lbh_data:
                        lbh_list = parse_lbh_data(scanned.lbh_data)

                        if lbh_list:
                            vol_weight = calculate_vol_weight(
                                lbh_list,
                                mode
                            )

                    final_weight = max(delivery_weight, vol_weight)

                    vol_weights.append(vol_weight)
                    final_weights.append(final_weight)

                merged_df["Vol Weight"] = vol_weights
                merged_df["Final Weight"] = final_weights

                # ---------- Final column order ----------
                merged_df = merged_df[
                    [
                        "Company Name",
                        "Docket No",
                        "Booking Date",
                        "Pin Code",
                        "No.of Pieces",
                        "Weight",        # Delivery weight
                        "Vol Weight",    # LBH calculated
                        "Final Weight",  # max(Weight, Vol Weight)
                        "Mode",
                        "Destination City",
                        "Document Type",
                    ]
                ]

                # ---------- Download ----------
                response = HttpResponse(
                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                response["Content-Disposition"] = (
                    'attachment; filename="merged_excel.xlsx"'
                )

                merged_df.to_excel(response, index=False)
                return response

            except Exception as e:
                message = f"Merge failed: {str(e)}"

    return render(request, 'merge_excel.html', {
        'message': message
    })
