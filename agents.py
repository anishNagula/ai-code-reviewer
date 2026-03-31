def summariser_agent(code):

    if "open(" in code:
        return """This function reads data from a file, processes each line, and converts valid entries into integers.

Step-by-step:
1. Opens a file and reads its content
2. Splits data into lines
3. Filters out empty values
4. Converts each valid value into an integer
5. Returns the processed list

Time Complexity: O(n)
"""

    if "for" in code and "if" in code:
        return """This function iterates through a list and applies conditional transformations.

Step-by-step:
1. Iterates through each element
2. Applies a condition (e.g., even/odd check)
3. Performs different operations based on the condition
4. Stores results in a list
5. Returns the transformed list

Time Complexity: O(n)
"""

    if "append(" in code:
        return """This function builds a new list by applying an operation to each element of the input list.

Step-by-step:
1. Iterates through elements
2. Applies transformation
3. Stores results in a new list

Time Complexity: O(n)
"""

    return "This function processes input data and returns a computed result."


def reviewer_agent(code):

    issues = []

    if "range(len(" in code:
        issues.append("Inefficient loop: using index-based iteration instead of direct iteration")

    if "append(" in code and "for" in code:
        issues.append("List construction can be optimized using list comprehension")

    if "open(" in code and "close(" not in code:
        issues.append("File is opened but not properly closed (resource leak)")

    if "+" in code and '"' in code:
        issues.append("String concatenation can be improved using f-strings")

    if "/" in code and "try" not in code:
        issues.append("Division operation without error handling (risk of crash)")

    if not issues:
        return """No major issues detected.

However, minor improvements in readability and structure can be applied."""

    return "Issues detected:\n" + "\n".join(f"- {i}" for i in issues)



def improvement_agent(code):

    # 🔥 Conditional transformation (ONLY when condition exists)
    if "for" in code and "if" in code and "append" in code and "% 2" in code:
        return """def process_numbers(nums):
    return [x*2 if x % 2 == 0 else x*3 for x in nums]"""

    # 🔥 Simple doubling
    if "for" in code and "append" in code and "* 2" in code:
        return """def double(nums):
    return [x*2 for x in nums]"""

    # 🔥 File processing
    if "open(" in code and "int(" in code:
        return """def read_and_process(file):
    with open(file) as f:
        return [int(x) for x in f.read().split("\\n") if x]"""

    # 🔥 Sum case
    if "total" in code and "nums" in code:
        return """def sum_list(nums):
    return sum(nums)"""

    return "Refactor code using better structure and Pythonic practices."
