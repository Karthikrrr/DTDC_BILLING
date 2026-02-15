import calendar
import os
import datetime
import pandas as pd
from decimal import Decimal
import json

from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt

from weasyprint import HTML
from django.template.loader import render_to_string

from .models import Company, Bill, Invoice, PincodeFile
from .excel_engine import (
    load_cal_df,
    load_latest_pincode_df,
    get_segment_from_pincode,
    get_price_by_segment_and_weight,
)


@login_required
def dashboard(request):
    return render(request, "billing/dashboard.html")



def detect_pincode_column(df):
    aliases = ["PINCODE", "PIN CODE", "PIN", "ZIP", "POSTAL", "POSTAL CODE"]
    for col in df.columns:
        col_u = str(col).strip().upper()
        if any(a in col_u for a in aliases):
            return col
    return None



def apply_segment_suffix(segment, docket_no, mode):
    """
    Apply business rules to modify segment.
    Priority:
    1. Docket starts with 'G' → GEC
    2. Mode = SURFACE → R
    3. Mode = AIR CARGO → A
    """

    docket_no = str(docket_no).strip().upper()
    mode = str(mode).strip().upper()

    if docket_no.startswith("G"):
        return f"{segment} GEC"

    if mode == "SURFACE":
        return f"{segment} R"

    if mode == "AIR CARGO":
        return f"{segment} A"

    return segment


@staff_member_required
def upload_monthly(request):

    if request.method == "POST":
        file = request.FILES.get("file")
        if not file:
            messages.error(request, "Upload Excel File")
            return redirect("billing:upload_monthly")

        try:
            df = pd.read_excel(file)
        except:
            file.seek(0)
            df = pd.read_csv(file)

        original_headers = df.columns
        df.columns = [str(c).strip().upper() for c in df.columns]


        bill_name = request.POST.get("bill_name")
        invoice = None

        if bill_name:
            invoice, _ = Invoice.objects.get_or_create(
                name=bill_name.strip()
            )

        def find(col_set): 
            for c in df.columns: 
                if c in col_set: return c
            return None

        company_col = find({"COMPANY NAME", "COMPANY", "CLIENT"})
        docket_col  = find({"DOCKET NO", "CONSIGNMENT NUMBER", "LR NO"})
        date_col    = find({"BOOKING DATE", "DATE"})
        pincode_col = find({"PIN CODE", "PINCODE"})
        pieces_col  = find({"NO OF PIECES", "NO.OF PIECES", "PIECES", "QTY"})
        manifest_weight = find({"WEIGHT"})
        vol_weight  = find({"VOL WEIGHT", "VOLUME WEIGHT"})
        weight_col  = find({"FINAL WEIGHT", "CHARGEABLE WEIGHT"})
        mode_col    = find({"MODE", "SHIPMENT MODE", "TRANSPORT MODE"})
        dest_col    = find({"DESTINATION CITY"})
        doc_type = find({"DOCUMENT TYPE"})


        missing = [k for k,v in {
            "COMPANY NAME":company_col,
            "DOCKET NO":docket_col,
            "BOOKING DATE":date_col,
            "PINCODE":pincode_col
        }.items() if v is None]

        if missing:
            messages.error(request, f"Missing Columns: {missing}\nFound: {original_headers}")
            return redirect("billing:upload_monthly")

        try:
            month = pd.to_datetime(df.iloc[0][date_col]).strftime("%Y-%m")
        except:
            month = datetime.date.today().strftime("%Y-%m")

        try:
            pincode_df = load_latest_pincode_df(PincodeFile)
        except Exception as e:
            messages.error(request, f"Pincode File Error: {e}")
            return redirect("billing:upload_monthly")

        created, updated = 0, 0

        for _, row in df.iterrows():
            try:
                company = Company.objects.get(
                    name__iexact=str(row[company_col]).strip()
                )
            except:
                continue


            docket = str(row[docket_col]).strip()

            try:
                date_val = pd.to_datetime(row[date_col]).date()
            except:
                date_val = datetime.date.today()

            dest    = str(row.get(dest_col, "")).strip() if dest_col else ""
            pincode = str(row[pincode_col]).strip()
            pieces  = int(row.get(pieces_col, 1)) if pieces_col else 1
            weight  = float(row.get(weight_col, 0)) if weight_col else 0
            mani_weight = float(row.get(manifest_weight,0)) if manifest_weight else 0
            volum_weight = float(row.get(vol_weight,0)) if vol_weight else 0
            mode    = str(row.get(mode_col, "")).strip().upper() if mode_col else ""
            doc_typ = str(row.get(doc_type, "")).strip() if doc_type else "NONE"

            try:
                cal_df = load_cal_df(company.rule_file.path)
            except:
                continue

            base_segment = get_segment_from_pincode(pincode_df, pincode)
            segment = apply_segment_suffix(base_segment, docket, mode)
            price = get_price_by_segment_and_weight(cal_df, segment, weight)
            amount = Decimal(price * pieces).quantize(Decimal("0.01")) if price else Decimal("0.00")
            fsc_percent = Decimal(company.fsc_percent or 0)
            fsc_amount = (amount * fsc_percent / 100).quantize(Decimal("0.01"))
            docket = str(row[docket_col]).strip().upper()
            month = date_val.strftime("%Y-%m")
            

            try:
                obj, new = Bill.objects.update_or_create(
                    company=company,
                    docket_no=docket,
                    month=month,
                    defaults={
                        "invoice": invoice,
                        "date": date_val,
                        "destination": dest,
                        "pincode": pincode,
                        "segment": segment,
                        "pieces": pieces,
                        "manifest_weight": mani_weight,
                        "vol_weight": volum_weight,
                        "weight": weight,
                        "amount": amount,
                        "fsc_amount": fsc_amount,
                        "mode": mode,
                        "doc_type":doc_typ
                    }
                )
                created += int(new)
                updated += int(not new)

            except Exception as e:
                # Final safety: update manually
                Bill.objects.filter(
                    company=company,
                    docket_no=docket,
                    month=month
                ).update(
                    date=date_val,
                    destination=dest,
                    pincode=pincode,
                    segment=segment,
                    pieces=pieces,
                    manifest_weight=mani_weight,
                    vol_weight=volum_weight,
                    weight=weight,
                    amount=amount,
                    fsc_amount=fsc_amount,
                    mode=mode,
                    doc_type=doc_typ
                )
                updated += 1

        messages.success(
            request, f"Upload Complete ✓ Created:{created} | Updated:{updated}"
        )
        return redirect("billing:upload_monthly")

    return render(request, "billing/upload_monthly.html")


# ----------------------------------------
#  REPORT PAGE → dropdown page
# ----------------------------------------

@staff_member_required
def download_report_page(request):
    return render(request, "billing/download_report.html", {
        "companies": Company.objects.all(),
        "invoices": Invoice.objects.all().order_by("-created_at"),
        "months": Bill.objects.values_list("month", flat=True).distinct(),
    })

@staff_member_required
def invoice_preview_by_invoice(request, invoice_id):
    from .models import Invoice

    try:
        invoice = Invoice.objects.get(id=invoice_id)
    except Invoice.DoesNotExist:
        return HttpResponse("Invoice not found", status=404)

    bills = Bill.objects.filter(invoice=invoice).select_related("company").order_by("date")

    if not bills.exists():
        return HttpResponse("No bills found for this invoice.")

    # Use first bill's company for header display
    company = bills.first().company

    return render(
        request,
        "billing/invoice_builder.html",
        {
            "company": company,        
            "bills": bills,            
            "month": invoice.name,    
            "today": datetime.date.today().isoformat(),
            "invoice": invoice,
        }
    )

3
# ----------------------------------------
#  Update Bill Data (SESSION BASED - No DB updates)
# ----------------------------------------
@staff_member_required
@csrf_exempt
def update_bill_data(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)

    try:
        data = json.loads(request.body)
        bill_id = data.get("bill_id")
        field = data.get("field")
        value = data.get("value")

        bill = Bill.objects.get(id=bill_id)

        # =========================
        # 1️⃣ Handle editable fields
        # =========================
        if field == "pieces":
            bill.pieces = int(value or 0)

        elif field in ["weight", "manifest_weight", "vol_weight"]:
            setattr(bill, field, float(value or 0))

        elif field == "oda_charges":
            bill.oda_charges = float(value or 0)

        elif field == "inv_amount":
            raw = str(value).strip()

            if "*" in raw:
                base, percent = raw.split("*")
                base = float(base)
                percent = float(percent)
            else:
                base = float(raw or 0)
                percent = 3

            bill.inv_amount = base
            bill.inv_amt_percent = round((base * percent) / 100, 2)

        elif field == "amount":
            base_amount = float(value or 0)

            fsc_percent = getattr(bill.company, "fsc_percent", 0) or 0
            bill.fsc_amount = round((base_amount * fsc_percent) / 100, 2)

            # ✅ ACCUMULATIVE FORMULA
            bill.amount = round(
                base_amount
                + float(bill.fsc_amount or 0)
                + float(bill.oda_charges or 0)
                + float(bill.inv_amt_percent or 0),
                2
            )

            bill.save()

            return JsonResponse({
                "status": "success",
                "segment": bill.segment,
                "amount": bill.amount,
                "fsc_amount": bill.fsc_amount,
                "inv_amt_percent": bill.inv_amt_percent or 0
            })

        elif field != "__recalculate__":
            setattr(bill, field, value)

        # =========================
        # 2️⃣ Reload engines
        # =========================
        cal_df = load_cal_df(bill.company.rule_file.path)
        pincode_df = load_latest_pincode_df(PincodeFile)

        # =========================
        # 3️⃣ Segment calculation
        # =========================
        base_segment = get_segment_from_pincode(
            pincode_df, bill.pincode
        )

        bill.segment = apply_segment_suffix(
            base_segment,
            bill.docket_no,
            bill.mode
        )

        # =========================
        # 4️⃣ Base amount calculation
        # =========================
        price = get_price_by_segment_and_weight(
            cal_df,
            bill.segment,
            bill.weight
        )

        base_amount = round(price * bill.pieces, 2) if price else 0

        # =========================
        # 5️⃣ FSC calculation
        # =========================
        fsc_percent = getattr(bill.company, "fsc_percent", 0) or 0
        bill.fsc_amount = round((base_amount * fsc_percent) / 100, 2)

        # =========================
        # 6️⃣ FINAL AMOUNT (ACCUMULATIVE) ✅
        # =========================
        bill.amount = round(
            base_amount
            + float(bill.fsc_amount or 0)
            + float(bill.oda_charges or 0)
            + float(bill.inv_amt_percent or 0),
            2
        )

        bill.save()

        return JsonResponse({
            "status": "success",
            "segment": bill.segment,
            "amount": bill.amount,
            "fsc_amount": bill.fsc_amount,
            "inv_amt_percent": bill.inv_amt_percent or 0
        })

    except Bill.DoesNotExist:
        return JsonResponse({"error": "Bill not found"}, status=404)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ----------------------------------------
#  Create New Bill (SESSION BASED - No DB updates)
# ----------------------------------------
@staff_member_required
@csrf_exempt
def create_bill(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            company_id = data.get('company_id')
            month = data.get('month')
            
            # Generate a temporary ID for session storage
            temp_id = f"temp_{datetime.datetime.now().timestamp()}"
            
            # Store in session
            session_key = f'bill_edits_{temp_id}'
            request.session[session_key] = {
                'docket_no': f"NEW-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
                'date': datetime.date.today().isoformat(),
                'destination': "",
                'pincode': "",
                'segment': "",
                'pieces': 0,
                'weight': 0,
                'amount': 0,
                'is_temp': True
            }
            request.session.modified = True
            
            return JsonResponse({
                'status': 'success', 
                'message': 'Bill created successfully (Session)',
                'bill_id': temp_id
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request'})


# ----------------------------------------
#  Delete Bill (SESSION BASED - No DB updates)
# ----------------------------------------
@staff_member_required
@csrf_exempt
def delete_bill(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            bill_id = data.get('bill_id')
            
            # Remove from session if it exists
            session_key = f'bill_edits_{bill_id}'
            if session_key in request.session:
                del request.session[session_key]
                request.session.modified = True
            
            return JsonResponse({'status': 'success', 'message': 'Bill deleted successfully (Session)'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request'})


# ----------------------------------------
#  Clear All Edits (SESSION BASED)
# ----------------------------------------
@staff_member_required
@csrf_exempt
def clear_edits(request):
    if request.method == "POST":
        try:
            # Clear all bill edits from session
            keys_to_remove = []
            for key in request.session.keys():
                if key.startswith('bill_edits_'):
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del request.session[key]
            
            request.session.modified = True
            
            return JsonResponse({'status': 'success', 'message': 'All edits cleared successfully'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request'})


# ----------------------------------------
#  Get edited bills from session
# ----------------------------------------
def get_edited_bills(request, original_bills):
    edited_bills = []
    
    for bill in original_bills:
        session_key = f'bill_edits_{bill.id}'
        if session_key in request.session:
            edits = request.session[session_key]
            # Create a modified bill object with edits
            edited_bill = {
                'id': bill.id,
                'docket_no': edits.get('docket_no', bill.docket_no),
                'date': edits.get('date', bill.date),
                'destination': edits.get('destination', bill.destination),
                'pincode': edits.get('pincode', bill.pincode),
                'segment': edits.get('segment', bill.segment),
                'pieces': edits.get('pieces', bill.pieces),
                'weight': edits.get('weight', bill.weight),
                'amount': edits.get('amount', bill.amount),
            }
            edited_bills.append(edited_bill)
        else:
            edited_bills.append({
                'id': bill.id,
                'docket_no': bill.docket_no,
                'date': bill.date,
                'destination': bill.destination,
                'pincode': bill.pincode,
                'segment': bill.segment,
                'pieces': bill.pieces,
                'weight': bill.weight,
                'amount': bill.amount,
            })
    
    # Add temporary bills
    for key in request.session.keys():
        if key.startswith('bill_edits_temp_'):
            edits = request.session[key]
            if edits.get('is_temp'):
                edited_bills.append({
                    'id': key.replace('bill_edits_', ''),
                    'docket_no': edits.get('docket_no', ''),
                    'date': edits.get('date', datetime.date.today()),
                    'destination': edits.get('destination', ''),
                    'pincode': edits.get('pincode', ''),
                    'segment': edits.get('segment', ''),
                    'pieces': edits.get('pieces', 0),
                    'weight': edits.get('weight', 0),
                    'amount': edits.get('amount', 0),
                    'is_temp': True
                })
    
    return edited_bills


# Number → Words
def _amount_to_words(amount):
    """Convert amount to words with proper formatting"""
    units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]
    teens = ["Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", 
             "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def convert_below_thousand(n):
        if n == 0:
            return ""
        elif n < 10:
            return units[n]
        elif n < 20:
            return teens[n-10]
        elif n < 100:
            return tens[n//10] + (" " + units[n%10] if n%10 != 0 else "")
        else:
            return units[n//100] + " Hundred" + (" " + convert_below_thousand(n%100) if n%100 != 0 else "")

    def convert_number(n):
        if n == 0:
            return "Zero"
        
        parts = []
        
        # Crores
        if n >= 10000000:
            parts.append(convert_below_thousand(n // 10000000) + " Crore")
            n %= 10000000
        
        # Lakhs
        if n >= 100000:
            parts.append(convert_below_thousand(n // 100000) + " Lakh")
            n %= 100000
        
        # Thousands
        if n >= 1000:
            parts.append(convert_below_thousand(n // 1000) + " Thousand")
            n %= 1000
        
        # Hundreds and below
        if n > 0:
            parts.append(convert_below_thousand(n))
        
        return " ".join(parts)

    amount = Decimal(str(amount)).quantize(Decimal("0.00"))
    rupees = int(amount)
    paisa = int((amount - rupees) * 100)

    result = convert_number(rupees) + " Rupees"
    if paisa > 0:
        result += " and " + convert_number(paisa) + " Paise"
    
    return result + " Only"

@staff_member_required
def invoice_generate_final_pdf(request):
    if request.method != "POST":
        return HttpResponse("Invalid Request", status=400)

    company_id = request.POST.get("company_id")
    month = request.POST.get("month")
    invoice_id = request.POST.get("invoice_id")

    invoice_no = request.POST.get("inv_no") or "101-101"
    invoice_due_date = request.POST.get("inv_due_date") or datetime.date.today()

    inv_date_str = request.POST.get("inv_date")

    if inv_date_str:
        invoice_date = datetime.datetime.strptime(inv_date_str, "%Y-%m-%d").date()
    else:
        invoice_date = datetime.date.today()

    # Tax amounts from frontend
    gst_amount = Decimal(request.POST.get("gst_amount", "0") or "0")
    cgst_amount = Decimal(request.POST.get("cgst_amount", "0") or "0")
    igst_amount = Decimal(request.POST.get("igst_amount", "0") or "0")

    # Fetch bills
    if invoice_id:
        bills = Bill.objects.filter(invoice_id=invoice_id)
    else:
        bills = Bill.objects.filter(company_id=company_id, month=month)

    if not bills.exists():
        return HttpResponse("No bills found")

    company = bills.first().company

    subtotal = Decimal("0.00")
    total_pieces = 0
    total_weight = Decimal("0.00")

    for b in bills:
        subtotal += Decimal(b.amount or 0)
        total_pieces += b.pieces or 0
        total_weight += Decimal(b.weight or 0)

    # Subtotal itself is taxable
    taxable_value = subtotal.quantize(Decimal("0.01"))

    grand_total = (
        taxable_value + gst_amount + cgst_amount + igst_amount
    ).quantize(Decimal("0.01"))

    year = invoice_date.year
    month_num = invoice_date.month

    start_date = datetime.date(year, month_num, 1)
    last_day = calendar.monthrange(year, month_num)[1]
    end_date = datetime.date(year, month_num, last_day)

    period = f"{start_date.strftime('%d/%m/%Y')} To {end_date.strftime('%d/%m/%Y')}"

    html = render_to_string(
        "billing/final_invoice_pdf.html",
        {
            "company": company,
            "bills": bills,

            "invoice_no": invoice_no,
            "invoice_date": invoice_date,
            "inv_due_date": invoice_due_date,
            "period": period,

            "subtotal": taxable_value,
            "gst_amount": gst_amount,
            "cgst_amount": cgst_amount,
            "igst_amount": igst_amount,

            "grand_total": grand_total,
            "total_in_words": _amount_to_words(grand_total),

            "total_pieces": total_pieces,
            "total_weight": total_weight,
        }
    )

    pdf = HTML(
        string=html,
        base_url=request.build_absolute_uri()
    ).write_pdf()

    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="Invoice_{company.name}_{month}.pdf"'
    )

    return response



@staff_member_required
def generate_pdf(request):
    if request.method == "POST":
        html = request.POST.get("html")
        pdf = HTML(string=html).write_pdf()

        response = HttpResponse(pdf,content_type="application/pdf")
        response['Content-Disposition']="attachment; filename=Invoice_Final.pdf"
        return response

    return HttpResponse("Invalid Request")



@staff_member_required
@csrf_exempt
def recalculate_bill(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)

    try:
        data = json.loads(request.body)
        bill_id = str(data.get("bill_id"))

        # Get original bill if exists
        bill = None
        if not bill_id.startswith("temp_"):
            bill = Bill.objects.get(id=bill_id)

        # Load session edits
        session_key = f"bill_edits_{bill_id}"
        edits = request.session.get(session_key, {})

        # Merge data (session overrides DB)
        docket_no = edits.get("docket_no", bill.docket_no if bill else "")
        pincode   = edits.get("pincode", bill.pincode if bill else "")
        weight    = float(edits.get("weight", bill.weight if bill else 0))
        pieces    = int(edits.get("pieces", bill.pieces if bill else 1))
        mode      = edits.get("mode", "")  # optional future use

        company = bill.company if bill else None
        if not company:
            return JsonResponse({"error": "Company not found"}, status=400)

        # Load required engines
        cal_df = load_cal_df(company.rule_file.path)
        pincode_df = load_latest_pincode_df(PincodeFile)

        # SEGMENT LOGIC
        base_segment = get_segment_from_pincode(pincode_df, pincode)
        final_segment = apply_segment_suffix(base_segment, docket_no, mode)

        # PRICE LOGIC (FIXED SLAB LOGIC)
        price = get_price_by_segment_and_weight(cal_df, final_segment, weight)
        amount = round(price * pieces, 2) if price else 0

        # Save back to session
        edits.update({
            "segment": final_segment,
            "amount": amount,
        })
        request.session[session_key] = edits
        request.session.modified = True

        return JsonResponse({
            "status": "success",
            "segment": final_segment,
            "amount": amount
        })

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
