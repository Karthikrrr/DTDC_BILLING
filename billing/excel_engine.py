# billing/excel_engine.py
import re
import math
import pandas as pd

# -------------------------
# Helpers: range parsing
# -------------------------
_NUM_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)")

def _parse_range(range_str):
    """
    Parse a weight range string into (min_val, max_val).
    Returns (None, None) if cannot parse.
    Supports:
      - "0.000-0.500"
      - "0.500 – 1.000" (en dash)
      - "0.500 to 1.000"
      - "10+" -> (10, inf)
      - single number -> (value, value) (treated conservatively)
    """
    if range_str is None:
        return (None, None)
    s = str(range_str).strip()
    if not s:
        return (None, None)

    # normalize dashes and words
    s = s.replace("–", "-").replace("—", "-").replace(" TO ", "-").replace(" to ", "-")
    s = s.replace("KG", "").replace("KGS", "").replace("kgs", "").replace("kg", "").strip()

    # handle "10+" "10 +"
    if "+" in s and _NUM_RE.search(s):
        m = _NUM_RE.search(s)
        try:
            min_v = float(m.group(1))
            return (min_v, math.inf)
        except:
            return (None, None)

    # find all numbers
    nums = _NUM_RE.findall(s)
    if not nums:
        return (None, None)
    if len(nums) == 1:
        try:
            v = float(nums[0])
            return (v, v)
        except:
            return (None, None)
    try:
        a = float(nums[0])
        b = float(nums[1])
        if a <= b:
            return (a, b)
        else:
            return (b, a)
    except:
        return (None, None)


# -------------------------
# Load company cal file
# -------------------------
def load_cal_df(path):
    """
    Load a company's calculation Excel (cal.xlsx).
    Tries to detect DESTINATION, RANGE/WEIGHT RANGE, PRICE/AMOUNT columns flexibly.
    Returns a DataFrame with normalized columns:
      DESTINATION (upper), RANGE (original string), START (float or None), END (float or None), PRICE (float)
    Raises ValueError if required columns not found.
    """
    df = pd.read_excel(path, engine="openpyxl")
    # Normalize header names (strip only, don't upper yet to help matching)
    df = df.rename(columns=lambda c: str(c).strip())
    cols = [c.strip().upper() for c in df.columns]

    # find destination-like column
    dest_col = None
    for orig, up in zip(df.columns, cols):
        if "DESTIN" in up or "SEGMENT" in up or up in ("DESTINATION", "ZONE"):
            dest_col = orig
            break

    # find range-like column
    range_col = None
    for orig, up in zip(df.columns, cols):
        if "RANGE" in up or "WEIGHT" in up or "KG" in up:
            range_col = orig
            break

    # find price-like column
    price_col = None
    for orig, up in zip(df.columns, cols):
        if "PRICE" in up or "AMOUNT" in up or "RATE" in up:
            price_col = orig
            break

    if not dest_col or not range_col or not price_col:
        raise ValueError(f"cal.xlsx missing required columns. Found cols: {list(df.columns)}")

    # normalize dataframe
    cal = df[[dest_col, range_col, price_col]].copy()
    cal.columns = ["DESTINATION", "RANGE", "PRICE"]
    # ensure strings
    cal["DESTINATION"] = cal["DESTINATION"].astype(str).str.upper().str.strip()
    cal["RANGE"] = cal["RANGE"].astype(str).str.strip()
    # coerce price where possible
    def _to_float(v):
        try:
            return float(v)
        except:
            try:
                return float(str(v).strip())
            except:
                return None
    cal["PRICE"] = cal["PRICE"].apply(_to_float)

    # parse ranges to START/END
    starts = []
    ends = []
    for r in cal["RANGE"]:
        s, e = _parse_range(r)
        starts.append(s)
        ends.append(e)
    cal["START"] = starts
    cal["END"] = ends

    return cal


# -------------------------
# Load latest pincode file (model-based)
# -------------------------
def load_latest_pincode_df(PincodeFileModel):
    """
    Given the PincodeFile Django model, read the latest uploaded file
    and return a cleaned dataframe with columns: PINCODE (string), SEGMENT (upper).
    Supports multiple sheets — picks first sheet that contains the required columns.
    Raises ValueError if none of the sheets contain the required columns.
    """
    latest = PincodeFileModel.objects.order_by("-uploaded_at").first()
    if not latest:
        return None

    xls = pd.ExcelFile(latest.file.path)

    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet)
        # normalize headers and values
        df = df.rename(columns=lambda c: str(c).strip().upper())
        df = df.applymap(lambda x: str(x).strip() if pd.notna(x) else "")

        # flexible detection
        pincode_col = next((c for c in df.columns if "PINCODE" in c or "PIN CODE" in c or c == "PIN"), None)
        segment_col = next((c for c in df.columns if "SEGMENT" in c or "ZONE" in c or "REGION" in c), None)

        if pincode_col and segment_col:
            tmp = df[[pincode_col, segment_col]].copy()
            tmp.columns = ["PINCODE", "SEGMENT"]
            tmp["PINCODE"] = tmp["PINCODE"].astype(str).str.strip()
            tmp["SEGMENT"] = tmp["SEGMENT"].astype(str).str.strip().str.upper()
            return tmp

    # no valid sheet
    raise ValueError("Pincode Excel must contain 'PINCODE' and 'SEGMENT' columns in at least one sheet.")


# -------------------------
# Get segment from pincode dataframe (safe)
# -------------------------
def get_segment_from_pincode(pincode_df, pincode):
    """
    Return the SEGMENT (uppercased string) for the given pincode value using pincode_df
    pincode_df expected to have columns PINCODE, SEGMENT
    Returns None if not found.
    Includes special mapping: if segment text contains 'PUNE' we convert to 'NON METROS'
    (based on your business rule).
    """
    if pincode_df is None:
        return None
    if pincode is None:
        return None

    p = str(pincode).strip()
    if not p:
        return None

    # ensure PINCODE dtype is string
    df = pincode_df.copy()
    df["PINCODE"] = df["PINCODE"].astype(str).str.strip()
    row = df[df["PINCODE"] == p]
    if row.empty:
        # try partial match on left side or district match fallback
        # (if pincode not matched exactly, we don't guess; return None)
        return None

    seg_val = row.iloc[0]["SEGMENT"]
    if isinstance(seg_val, pd.Series):
        seg_val = seg_val.iloc[0]
    seg = str(seg_val).strip().upper()

    # special business rule: if the segment value indicates 'PUNE' map to NON METROS
    # (this preserves existing 'METROS'/'NON METROS' values otherwise)
    if seg == "PUNE" or "PUNE" in seg:
        return "NON METROS"

    return seg


# -------------------------
# Price lookup: segment + weight
# -------------------------
def get_price_by_segment_and_weight(cal_df, segment, weight):
    """
    cal_df: DataFrame returned by load_cal_df
    segment: string like 'METROS' or 'NON METROS' etc.
    weight: numeric (kg)
    Returns price (float) or None.
    """
    if segment is None or segment == "":
        return None
    if weight is None:
        return None

    try:
        w = float(weight)
    except:
        return None

    # ensure DESTINATION normalized
    cal = cal_df.copy()
    cal["DESTINATION"] = cal["DESTINATION"].astype(str).str.upper().str.strip()

    subset = cal[cal["DESTINATION"] == str(segment).upper().strip()]
    if subset.empty:
        # try substring contains match (destination may be 'BANGALORE METROS' etc)
        subset = cal[cal["DESTINATION"].str.contains(str(segment).upper().strip(), na=False)]

    if subset.empty:
        return None

    # iterate rows and match ranges
    for _, r in subset.iterrows():
        start = r.get("START", None)
        end = r.get("END", None)

        # defensive handling
        try:
            if start is None or end is None:
                continue
            if start <= w <= (end if not math.isinf(end) else float("inf")):
                price = r.get("PRICE", None)
                try:
                    return float(price) if price is not None else None
                except:
                    try:
                        return float(str(price).strip())
                    except:
                        return None
        except Exception:
            # skip problematic rows
            continue

    return None
