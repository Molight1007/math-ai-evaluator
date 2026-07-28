"""Tests for user_agent import and initialization."""

import json

import pytest

from user_agent import ReasoningAgent


class FakeClient:
    def chat(self, messages, temperature=0.2, max_tokens=4096):
        return "分析：这是测试。\n最终答案：42"


def test_import_reasoning_agent():
    assert ReasoningAgent is not None


def test_init_with_fake_client():
    agent = ReasoningAgent(client=FakeClient())
    assert agent.client is not None
    assert agent.core is not None


def test_init_with_kwargs():
    agent = ReasoningAgent(client=FakeClient(), extra="ignored")
    assert agent is not None
