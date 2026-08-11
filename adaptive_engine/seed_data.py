from .models import Skill, ContentItem, ItemType
from .store import store


async def seed():
    """Upserts sample content — safe to call on every startup, won't duplicate."""
    skills = [
        Skill(id="py-basics", name="Python Basics", subject="coding"),
        Skill(id="py-functions", name="Functions", subject="coding", prerequisite_ids=["py-basics"]),
        Skill(id="py-loops", name="Loops", subject="coding", prerequisite_ids=["py-basics"]),
    ]
    for s in skills:
        await store.add_skill(s)

    items = [
        ContentItem(id="l1", skill_id="py-basics", item_type=ItemType.LESSON,
                    difficulty=0, payload={"body": "Variables store values: x = 5"}),
        ContentItem(id="q1", skill_id="py-basics", item_type=ItemType.QUESTION, difficulty=900,
                    payload={
                        "prompt": "What does x = 5 do?",
                        "choices": ["Assigns 5 to x", "Compares x to 5", "Deletes x", "Prints 5"],
                        "correct_index": 0,
                        "explanation": "In Python, a single = is the assignment operator. It takes the value on the right (5) and stores it in the variable on the left (x). Comparison uses == instead.",
                    }),
        ContentItem(id="q2", skill_id="py-basics", item_type=ItemType.QUESTION, difficulty=1100,
                    payload={
                        "prompt": "What type is 5.0 in Python?",
                        "choices": ["int", "float", "str", "bool"],
                        "correct_index": 1,
                        "explanation": "Any number written with a decimal point (like 5.0) is a float in Python, even if the value happens to be a whole number. Without the decimal point, 5 would be an int.",
                    }),
        ContentItem(id="q3", skill_id="py-basics", item_type=ItemType.QUESTION, difficulty=1300,
                    payload={
                        "prompt": "What is the result of 7 // 2?",
                        "choices": ["3.5", "3", "4", "1"],
                        "correct_index": 1,
                        "explanation": "// is floor division — it divides and rounds DOWN to the nearest whole number, discarding the remainder. 7 / 2 = 3.5, so 7 // 2 = 3.",
                    }),

        ContentItem(id="l2", skill_id="py-functions", item_type=ItemType.LESSON,
                    difficulty=0, payload={"body": "def greet():\n    return 'hi'"}),
        ContentItem(id="q4", skill_id="py-functions", item_type=ItemType.QUESTION, difficulty=1000,
                    payload={
                        "prompt": "Which keyword is used to define a function?",
                        "choices": ["func", "def", "fn", "function"],
                        "correct_index": 1,
                        "explanation": "Python uses 'def' (short for 'define') to start a function definition, followed by the function name and parentheses, e.g. def greet():",
                    }),
        ContentItem(id="q5", skill_id="py-functions", item_type=ItemType.QUESTION, difficulty=1250,
                    payload={
                        "prompt": "How does a function send a value back to whoever called it?",
                        "choices": ["print()", "return", "yield only", "output()"],
                        "correct_index": 1,
                        "explanation": "'return' immediately ends the function and hands a value back to the caller. print() just displays text — it doesn't give the caller anything to use afterward.",
                    }),

        ContentItem(id="l3", skill_id="py-loops", item_type=ItemType.LESSON,
                    difficulty=0, payload={"body": "for i in range(5):\n    print(i)"}),
        ContentItem(id="q6", skill_id="py-loops", item_type=ItemType.QUESTION, difficulty=1000,
                    payload={
                        "prompt": "range(?) loops 5 times, starting at 0",
                        "choices": ["4", "5", "6", "0"],
                        "correct_index": 1,
                        "explanation": "range(5) generates 0, 1, 2, 3, 4 — five numbers total. range() counts UP TO but not including its argument, so range(5) gives exactly 5 values starting from 0.",
                    }),
    ]
    for i in items:
        await store.add_item(i)