"""
script.py — Bitcoin scriptPubKey type classifier.

Classifies a raw scriptPubKey bytes object into a standard script type.
This is used for both transaction outputs AND for resolved prevouts
(from rev.dat) to classify input types.

Script type patterns:
  P2PKH:   OP_DUP OP_HASH160 <20 bytes> OP_EQUALVERIFY OP_CHECKSIG
           76 a9 14 <20b> 88 ac
  P2SH:    OP_HASH160 <20 bytes> OP_EQUAL
           a9 14 <20b> 87
  P2WPKH:  OP_0 <20 bytes>
           00 14 <20b>
  P2WSH:   OP_0 <32 bytes>
           00 20 <32b>
  P2TR:    OP_1 <32 bytes>
           51 20 <32b>
  P2PK:    <pubkey> OP_CHECKSIG
           <33b|65b> ac
  OP_RETURN: OP_RETURN ...
           6a ...

References:
    BIP16 (P2SH), BIP141 (P2WPKH/P2WSH), BIP341 (Taproot/P2TR)
"""

# Bitcoin Script opcodes used in pattern matching
OP_DUP          = 0x76
OP_HASH160      = 0xa9
OP_EQUALVERIFY  = 0x88
OP_CHECKSIG     = 0xac
OP_EQUAL        = 0x87
OP_RETURN       = 0x6a
OP_0            = 0x00
OP_1            = 0x51  # OP_1 = 0x51 (pushes 1 onto stack — used in P2TR)

# Script type string constants
TYPE_P2PKH     = "p2pkh"
TYPE_P2SH      = "p2sh"
TYPE_P2WPKH    = "p2wpkh"
TYPE_P2WSH     = "p2wsh"
TYPE_P2TR      = "p2tr"
TYPE_P2PK      = "p2pk"
TYPE_OP_RETURN = "op_return"
TYPE_UNKNOWN   = "unknown"


def classify_script(script: bytes) -> str:
    """
    Classify a scriptPubKey into a standard Bitcoin script type.

    Args:
        script: Raw scriptPubKey bytes.

    Returns:
        One of: "p2pkh", "p2sh", "p2wpkh", "p2wsh", "p2tr",
                "p2pk", "op_return", "unknown"
    """
    n = len(script)

    if n == 0:
        return TYPE_UNKNOWN

    # P2PKH — 25 bytes: OP_DUP OP_HASH160 <20B> OP_EQUALVERIFY OP_CHECKSIG
    if (n == 25
            and script[0] == OP_DUP
            and script[1] == OP_HASH160
            and script[2] == 0x14        # push 20 bytes
            and script[23] == OP_EQUALVERIFY
            and script[24] == OP_CHECKSIG):
        return TYPE_P2PKH

    # P2SH — 23 bytes: OP_HASH160 <20B> OP_EQUAL
    if (n == 23
            and script[0] == OP_HASH160
            and script[1] == 0x14        # push 20 bytes
            and script[22] == OP_EQUAL):
        return TYPE_P2SH

    # P2WPKH — 22 bytes: OP_0 0x14 <20B>
    if (n == 22
            and script[0] == OP_0
            and script[1] == 0x14):      # push 20 bytes
        return TYPE_P2WPKH

    # P2WSH — 34 bytes: OP_0 0x20 <32B>
    if (n == 34
            and script[0] == OP_0
            and script[1] == 0x20):      # push 32 bytes
        return TYPE_P2WSH

    # P2TR (Taproot) — 34 bytes: OP_1 0x20 <32B>
    if (n == 34
            and script[0] == OP_1
            and script[1] == 0x20):      # push 32 bytes
        return TYPE_P2TR

    # P2PK — compressed (35 bytes) or uncompressed (67 bytes)
    # Pattern: <pubkey> OP_CHECKSIG
    if n == 35 and script[0] == 0x21 and script[34] == OP_CHECKSIG:
        return TYPE_P2PK
    if n == 67 and script[0] == 0x41 and script[66] == OP_CHECKSIG:
        return TYPE_P2PK

    # OP_RETURN — data carrier output (unspendable)
    if script[0] == OP_RETURN:
        return TYPE_OP_RETURN

    return TYPE_UNKNOWN


def extract_op_return_data(script: bytes) -> bytes:
    """
    Extract the payload bytes from an OP_RETURN script.

    OP_RETURN scripts have the form:
        0x6a [length] [data...]

    Args:
        script: Raw scriptPubKey bytes starting with OP_RETURN (0x6a).

    Returns:
        The raw data payload bytes (empty if malformed).
    """
    if len(script) < 2 or script[0] != OP_RETURN:
        return b""
    # Skip OP_RETURN byte; the rest is the payload (may have a push opcode)
    return script[1:]
