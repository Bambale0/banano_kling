"""Unit tests for bot/states.py"""

import pytest

from bot.states import (AdminStates, BatchGenerationStates, GenerationStates,
                        ImageAnalyzerStates, PaymentStates)


def test_generation_states():
    """Test GenerationStates enum"""
    assert GenerationStates.waiting_for_input
    assert GenerationStates.waiting_for_image
    assert GenerationStates.waiting_for_video
    assert GenerationStates.waiting_for_video_prompt
    assert GenerationStates.waiting_for_reference_video
    assert GenerationStates.waiting_for_motion_character_image
    assert GenerationStates.waiting_for_motion_video
    assert GenerationStates.waiting_for_video_start_image
    assert GenerationStates.confirming_generation
    assert GenerationStates.selecting_batch_count
    assert GenerationStates.uploading_reference_images
    assert GenerationStates.uploading_reference_videos
    assert GenerationStates.confirming_reference_images
    assert GenerationStates.waiting_for_batch_image
    assert GenerationStates.waiting_for_batch_prompt
    assert GenerationStates.waiting_for_batch_aspect_ratio
    assert GenerationStates.selecting_duration
    assert GenerationStates.selecting_aspect_ratio
    assert GenerationStates.selecting_quality


def test_payment_states():
    """Test PaymentStates enum"""
    assert PaymentStates.selecting_package
    assert PaymentStates.confirming_payment
    assert PaymentStates.waiting_payment


def test_admin_states():
    """Test AdminStates enum"""
    assert AdminStates.waiting_broadcast_text
    assert AdminStates.confirming_broadcast
    assert AdminStates.waiting_user_id
    assert AdminStates.waiting_credits_amount


def test_batch_generation_states():
    """Test BatchGenerationStates enum"""
    assert BatchGenerationStates.selecting_mode
    assert BatchGenerationStates.selecting_preset
    assert BatchGenerationStates.entering_prompts
    assert BatchGenerationStates.uploading_references
    assert BatchGenerationStates.confirming_batch
    assert BatchGenerationStates.selecting_batch_count


def test_image_analyzer_states():
    """Test ImageAnalyzerStates enum"""
    assert ImageAnalyzerStates.waiting_for_photo
