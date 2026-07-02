"""Prompt templates for AIME benchmark."""

QUESTION_PROMPT = """\
Solve the following AIME (American Invitational Mathematics Examination) problem. \
AIME answers are always integers between 000 and 999 inclusive.

Problem:
{problem}

Think step by step. Show all your reasoning and calculations clearly. \
After your solution, state your final answer as an integer using the format: \
"The answer is \\boxed{{ANSWER}}" where ANSWER is an integer from 0 to 999.\
"""
