"""Detector library for the live event publisher.

Detectors are stateful and edge-triggered: they hold previous observations and
emit an Event only on the triggering edge. They perform NO I/O — de-duplication,
persistence, and delivery are handled by EventService.
"""
