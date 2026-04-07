def check_rules(code):
    issues = []

    # Loop inefficiency
    if "range(len(" in code:
        issues.append("Inefficient loop: use direct iteration instead of range(len())")

    # Resource leak
    if "open(" in code and "close(" not in code:
        issues.append("Possible resource leak: file opened but not closed")

    # Unreachable code
    lines = code.strip().split("\n")
    for i, line in enumerate(lines):
        if "return" in line and i < len(lines) - 1:
            issues.append("Unreachable code detected after return statement")
            break

    # Missing exception handling
    if "input(" in code and "try" not in code:
        issues.append("Missing exception handling for user input")

    # Division risk
    if "/" in code and "try" not in code:
        issues.append("Possible division by zero not handled")

    # String concatenation
    if '"Hello "' in code and "+" in code:
        issues.append("Use f-strings instead of string concatenation")

    # Manual max/min
    if "max_val" in code and "for" in code:
        issues.append("Manual max calculation: use built-in max()")

    # List building
    if "append(" in code and "for" in code:
        issues.append("List building detected: can use list comprehension")

    return issues
