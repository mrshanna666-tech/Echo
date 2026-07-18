# OpenAI Build Week Development Record

## Project

Echo Recorder is a local-first Windows activity journal focused on private memory reconstruction, reflection, and user-owned data.

## Pre-existing project disclosure

Echo development began before the OpenAI Build Week submission period. The submission represents a meaningful extension of the existing project, not a claim that every file was created during the event.

## Meaningful extensions during the submission period

Work completed or materially expanded from July 13, 2026 includes:

- memory replay around a selected time
- redesigned timeline, settings, and memory interfaces
- activity-session merging and categorization
- privacy exclusions, idle-time preferences, and local retention controls
- reliable SQLite backup and portable data export
- recovery of unfinished activity records
- handling of activity that crosses midnight
- automated tests for recorder reliability, replay selection, preferences, timeline behavior, database operations, and export integrity

## Use of Codex and GPT-5.6

Codex and GPT-5.6 were used for implementation, review, debugging, interface iteration, test design, and documentation during the submission period.

Evidence to retain:

- Codex task history and timestamps
- Git commits created during the submission period
- before-and-after screenshots that contain synthetic data only
- test output and build artifacts
- a short development narrative in the Devpost submission

## Validation

On July 18, 2026, the project imported successfully and all 13 automated `unittest` tests passed.

## Submission positioning

Recommended track: **Apps for Your Life**

Suggested one-line description:

> Echo is a privacy-first Windows activity journal that turns local application history, notes, and moments into a reconstructable memory of your day.

