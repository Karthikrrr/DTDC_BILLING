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

from .models import Company, Bill, PincodeFile
from .excel_engine import (
    load_cal_df,
    load_latest_pincode_df,
    get_segment_from_pincode,
    get_price_by_segment_and_weight,
)


# ----------------------------------------
#  DASHBOARD
# ----------------------------------------
@login_required
def dashboard(request):
    return render(request, "billing/dashboard.html")


# ----------------------------------------
#  Helper → Detect Pincode Field
# ----------------------------------------
def detect_pincode_column(df):
    aliases = ["PINCODE", "PIN CODE", "PIN", "ZIP", "POSTAL", "POSTAL CODE"]
    for col in df.columns:
        col_u = str(col).strip().upper()
        if any(a in col_u for a in aliases):
            return col
    return None


# ----------------------------------------
#   MONTHLY BILL UPLOAD & PROCESSING
# ----------------------------------------
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

        # Detect required columns (flexible)
        def find(col_set): 
            for c in df.columns: 
                if c in col_set: return c
            return None

        company_col  = find({"COMPANY NAME","COMPANY","CLIENT"})
        docket_col   = find({"CONSIGNMENT NUMBER","DOCKET NO","LR NO"})
        date_col     = find({"BOOKING DATE","DATE"})
        pincode_col  = detect_pincode_column(df)
        dest_col     = find({"DESTINATION","DESTINATION CITY","CITY"})
        pieces_col   = find({"NO.OF PIECES","PIECES","QTY"})
        weight_col   = find({"WEIGHT IN KGS","WEIGHT","CHARGEABLE WEIGHT"})

        missing = [k for k,v in {
            "COMPANY NAME":company_col,"DOCKET NO":docket_col,
            "BOOKING DATE":date_col,"PINCODE":pincode_col
        }.items() if v is None]

        if missing:
            messages.error(request, f"Missing Columns: {missing}\nFound: {original_headers}")
            return redirect("billing:upload_monthly")

        # Month infer
        try:
            month = pd.to_datetime(df.iloc[0][date_col]).strftime("%Y-%m")
        except:
            month = datetime.date.today().strftime("%Y-%m")

        # Load Pincode Database
        try:
            pincode_df = load_latest_pincode_df(PincodeFile)
        except Exception as e:
            messages.error(request, f"Pincode File Error: {e}")
            return redirect("billing:upload_monthly")

        created, updated = 0, 0

        for _, row in df.iterrows():
            try:
                company = Company.objects.get(name__iexact=str(row[company_col]).strip())
            except:
                continue

            docket = str(row[docket_col]).strip()

            try:
                date_val = pd.to_datetime(row[date_col]).date()
            except:
                date_val = datetime.date.today()

            dest     = str(row.get(dest_col, "")).strip() if dest_col else ""
            pincode  = str(row[pincode_col]).strip()
            pieces   = int(row.get(pieces_col,1)) if pieces_col else 1
            weight   = float(row.get(weight_col,0)) if weight_col else 0

            # Load cal file
            try:
                cal_df = load_cal_df(company.rule_file.path)
            except:
                continue

            # Extract segment
            segment = get_segment_from_pincode(pincode_df, pincode)

            # Price from segment+weight
            price = get_price_by_segment_and_weight(cal_df, segment, weight)

            amount = price * pieces if price else None

            # Save to DB
            with transaction.atomic():
                obj, new = Bill.objects.update_or_create(
                    company=company,
                    docket_no=docket,
                    month=month,
                    defaults={
                        "date":date_val,"destination":dest,"pincode":pincode,"segment":segment,
                        "pieces":pieces,"weight":weight,"amount":amount,
                    })
                created += new
                updated += (not new)

        messages.success(request, f"Upload Complete ✓ Created:{created} | Updated:{updated}")
        return redirect("billing:upload_monthly")

    return render(request,"billing/upload_monthly.html")


# ----------------------------------------
#  REPORT PAGE → dropdown page
# ----------------------------------------
@staff_member_required
def download_report_page(request):
    return render(request,"billing/download_report.html",{
        "companies":Company.objects.all(),
        "months":Bill.objects.values_list("month",flat=True).distinct(),
    })


# ----------------------------------------
#  Editable Invoice Preview Page
# ----------------------------------------
@staff_member_required
def invoice_preview(request, company_id, month):
    bills = Bill.objects.filter(company_id=company_id, month=month).order_by("date")

    if not bills.exists():
        return HttpResponse("No Records Found.")

    return render(request, "billing/invoice_builder.html", {
        "company": bills.first().company,
        "bills": bills,
        "month": month,
        "today": datetime.date.today().isoformat(),
    })


# ----------------------------------------
#  Update Bill Data (SESSION BASED - No DB updates)
# ----------------------------------------
@staff_member_required
@csrf_exempt
def update_bill_data(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            bill_id = data.get('bill_id')
            field = data.get('field')
            value = data.get('value')
            
            # Store in session instead of database
            session_key = f'bill_edits_{bill_id}'
            if session_key not in request.session:
                request.session[session_key] = {}
            
            request.session[session_key][field] = value
            request.session.modified = True
            
            return JsonResponse({'status': 'success', 'message': 'Updated successfully (Session)'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request'})


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
        return HttpResponse("❌ Invalid access")

    company_id = request.POST.get("company_id")
    month      = request.POST.get("month")

    invoice_no   = request.POST.get("invoice_number", f"HRS/25-26-{company_id}")
    invoice_date = request.POST.get("invoice_date", datetime.date.today())
    gst_value    = request.POST.get("gst", "18")  # Default to 18% IGST

    # Get original bills
    original_bills = Bill.objects.filter(company_id=company_id, month=month).order_by("date")
    if not original_bills.exists():
        return HttpResponse("❌ No bills found for month.")

    # Get edited bills from session
    edited_bills_data = get_edited_bills(request, original_bills)

    company = original_bills.first().company

    # Calculate totals from edited data
    total = Decimal(0)
    total_pieces = 0
    total_weight = Decimal(0)
    
    for bill_data in edited_bills_data:
        total += Decimal(bill_data.get('amount', 0) or 0)
        total_pieces += int(bill_data.get('pieces', 0) or 0)
        total_weight += Decimal(bill_data.get('weight', 0) or 0)

    # Calculate GST (IGST @ 18%)
    taxable_value = total
    gst_percent = Decimal(gst_value)
    gst_amount = (taxable_value * gst_percent) / Decimal(100)
    grand_total = taxable_value + gst_amount

    # Determine state codes (you might want to enhance this logic)
    def get_state_code(destination):
        state_mapping = {
            'BANGALORE': 'KA',
            'MYSORE': 'KA', 
            'DELHI': 'DL',
            'CHANDIGARH': 'CH',
            'PUNE': 'MH',
            'MALUR': 'KA',
            # Add more mappings as needed
        }
        for key, code in state_mapping.items():
            if key in destination.upper():
                return code
        return 'KA'  # Default to Karnataka

    # Add state codes to bill data
    for bill in edited_bills_data:
        bill['state'] = get_state_code(bill.get('destination', ''))

    html_string = render_to_string("billing/final_invoice_pdf.html", {
        "company": company,
        "bills": edited_bills_data,
        "invoice_no": invoice_no,
        "invoice_date": invoice_date,
        "period": f"01/{month.split('-')[1]}/20{month.split('-')[0]} To 30/{month.split('-')[1]}/20{month.split('-')[0]}",
        "total": taxable_value,
        "gst": gst_amount,
        "grand_total": grand_total,
        "total_in_words": _amount_to_words(grand_total),
        "total_pieces": total_pieces,
        "total_weight": total_weight,
    })

    # Generate PDF
    html = HTML(string=html_string, base_url=request.build_absolute_uri())
    
    pdf = html.write_pdf()

    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="Invoice_{company.name}_{month}.pdf"'
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