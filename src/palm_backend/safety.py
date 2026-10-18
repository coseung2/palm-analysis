"""Preserve schema-validated stories without keyword-based whole-result rejection.

Observation uncertainty and limits on unsupported claims remain in provider
instructions. This compatibility hook neither certifies factual accuracy nor
silently replaces the generated interpretation.
"""
from .models import Story


def validate_story(story: Story) -> Story:
    return story
