"""Prompt templates for ELAIPBench benchmark."""

SA_MCQ_PROMPT = """\
Please select the correct answer based on the paper content. Each question has only\
1 correct option.
Format your final answer as: "The correct answer is (X)" where X is a single letter."""

MA_MCQ_PROMPT = """\
Please select all correct answers based on the paper content. Each question has 2-3 \
correct options.

Format your final answer as: "The correct answers are (X, Y, ...)" listing \
all correct letters in alphabetical order, e.g. "The correct answers are (A, B, C)"."""
