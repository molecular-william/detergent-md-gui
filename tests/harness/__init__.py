"""Shared test construction: fixtures, the application factory, and the live-server helpers.

Nothing in this directory is collected as a test. The modules hold *construction* -- how to build an application, a
prepared run, a page -- and never meaning: a test file keeps its own arguments and its own assertions, because a copy
of a fixture drifts and a copy of an assertion does not exist.
"""
