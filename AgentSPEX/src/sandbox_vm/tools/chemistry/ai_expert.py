# Reimplementation of tool from https://github.com/OSU-NLP-Group/ChemToolAgent/blob/main/chemagent/tools/ai_expert.py
import os

from openai import OpenAI

SYSTEM_PROMPT = "You are an expert chemist. Your task is to answer the following question to your best ability. You can think step by step, and your answer should contain all the information necessary to answer the question."


def ask_ai_expert(question: str, model: str = "gpt-4-turbo-2024-04-09") -> dict:
    """
    An AI expert that can answer any chemistry questions. When there are no other tools
    that can meet your need, this tool can be used as the last resort.

    Args:
        question: The question to ask the AI expert
        model: OpenAI model to use (default: gpt-4-turbo-2024-04-09)

    Returns:
        {'output': 'expert answer'} on success, or {'error': 'error message'} on failure

    Examples:
        ask_ai_expert("What is the boiling point of water?")
        -> {"output": "The boiling point of water at standard atmospheric pressure..."}
    """
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return {"error": "OPENAI_API_KEY environment variable not set"}

        # Initialize OpenAI client
        client = OpenAI(api_key=api_key)

        # Create conversation
        conversation = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Question: " + question},
        ]

        # Make API call
        response = client.chat.completions.create(
            model=model, messages=conversation, temperature=0.2, timeout=60
        )

        # Extract answer
        answer = response.choices[0].message.content

        return {"output": answer}

    except Exception as e:
        return {"error": f"AI expert failed: {str(e)}"}
