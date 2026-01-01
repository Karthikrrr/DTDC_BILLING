import pandas as pd
from .models import ManifestRecord

def normalize(col):
    return col.strip().replace(" ", "_").replace("\n", "").upper()

def process_manifest(file, manifest_obj):
    df = pd.read_excel(file)

    # Normalize column names
    df.columns = [normalize(c) for c in df.columns]

    DOCKET_COL = None
    DATE_COL = None
    PINCODE_COL = None
    PIECES_COL = None

    for col in df.columns:
        if col == "DSR_CNNO":
            DOCKET_COL = col
        elif col == "DSR_BOOKING_DATE":
            DATE_COL = col
        elif col == "DSR_DEST_PIN":
            PINCODE_COL = col
        elif col == "DSR_NO_OF_PIECES":
            print(col.strip())
            PIECES_COL = col

    if not DOCKET_COL or not DATE_COL:
        raise ValueError(
            f"Required columns not found. Found columns: {list(df.columns)}"
        )

    for _, row in df.iterrows():
        docket = str(row[DOCKET_COL]).strip()

        if docket.lower() == "nan" or docket == "":
            continue

        # ---- PINCODE ----
        pincode = None
        if PINCODE_COL and not pd.isna(row[PINCODE_COL]):
            pincode = str(row[PINCODE_COL]).strip()

        # ---- PIECES ----
        pieces = None
        if PIECES_COL and not pd.isna(row[PIECES_COL]):
            # Handles 1 / 1.0 / "1"
            pieces = str(int(float(row[PIECES_COL])))

        ManifestRecord.objects.create(
            manifest=manifest_obj,
            docket_no=docket,
            manifest_date=pd.to_datetime(
                row[DATE_COL],
                dayfirst=True,
                errors="coerce"
            ).date(),
            pincode=pincode,
            pieces=pieces
        )
