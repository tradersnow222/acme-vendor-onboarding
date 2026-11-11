import re

# data-boundaries.mdc: never store bank account numbers, routing numbers, EIN/TIN, or SSNs.

REFERENCE_MESSAGE = (
    "Send only a reference such as 'W-9 received'. "
    "Do not send a bank account number, routing number, EIN, TIN, or SSN."
)

SSN_DASHED = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
SSN_SPACED = re.compile(r"\b\d{3}\s\d{2}\s\d{4}\b")
EIN_DASHED = re.compile(r"\b\d{2}-\d{7}\b")
LABELED_TAX = re.compile(
    r"\b(?:ssn|social security(?: number)?|ein|tin|tax id|tax identification(?: number)?)\b"
    r"[^0-9]{0,24}(\d{3}-\d{2}-\d{4}|\d{3}\s\d{2}\s\d{4}|\d{2}-\d{7}|\d{9})\b",
    re.I,
)
LABELED_ROUTING = re.compile(
    r"\b(?:routing(?: number)?|aba|rtn)\b[^0-9]{0,24}(\d{9})\b",
    re.I,
)
LABELED_ACCOUNT = re.compile(
    r"\b(?:bank account(?: number)?|account number|acct(?:\s*(?:number|#|no\.?))?)\b"
    r"[^0-9]{0,24}(\d[\d\s-]{6,22}\d)",
    re.I,
)
NINE_DIGITS = re.compile(r"\b\d{9}\b")
ROUTING_SPACED = re.compile(r"\b(\d{3})\s(\d{3})\s(\d{3})\b")
PHONE = re.compile(r"(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}\b")
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
URL = re.compile(r"https?://\S+")


class SensitiveDataError(ValueError):
    pass


def _in_url(text, start, end):
    return any(match.start() <= start and end <= match.end() for match in URL.finditer(text))


def _aba_valid(number):
    if len(number) != 9 or not number.isdigit():
        return False
    digits = [int(char) for char in number]
    total = (
        3 * (digits[0] + digits[3] + digits[6])
        + 7 * (digits[1] + digits[4] + digits[7])
        + (digits[2] + digits[5] + digits[8])
    )
    return total > 0 and total % 10 == 0


def _account_number(raw):
    if DATE.fullmatch(raw.strip()) or PHONE.fullmatch(raw.strip()):
        return False
    digits = re.sub(r"\D", "", raw)
    return 8 <= len(digits) <= 17


def find_sensitive(text):
    if not text:
        return []
    found = []

    def add(kind):
        if kind not in found:
            found.append(kind)

    if SSN_DASHED.search(text) or SSN_SPACED.search(text):
        add("ssn")
    if EIN_DASHED.search(text):
        add("ein")
    if LABELED_TAX.search(text):
        add("tax_id")
    if LABELED_ROUTING.search(text):
        add("routing")
    for match in LABELED_ACCOUNT.finditer(text):
        if _account_number(match.group(1)):
            add("account")
    for match in NINE_DIGITS.finditer(text):
        if not _in_url(text, match.start(), match.end()) and _aba_valid(match.group()):
            add("routing")
    for match in ROUTING_SPACED.finditer(text):
        if _in_url(text, match.start(), match.end()):
            continue
        if _aba_valid("".join(match.groups())):
            add("routing")
    return found


def checked_text(text):
    if find_sensitive(text):
        raise SensitiveDataError(REFERENCE_MESSAGE)
    return text
