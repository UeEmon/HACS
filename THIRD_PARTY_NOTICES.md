# Third-party components

HACS original code and accompanying documentation are licensed under Apache-2.0. This does not relicense third-party components or reference documents.

## Application dependencies

HACS currently uses Python standard-library modules and local HACS modules; no third-party pip packages or bundled JavaScript frameworks are required at runtime.

- **Python 3.12** (container runtime): Python Software Foundation License Version 2 and the applicable notices for incorporated components. Preserve the runtime's license and copyright notices when redistributing it. Official terms: https://docs.python.org/3.12/license.html
- **SQLite** (accessed through Python's `sqlite3` module): upstream SQLite is dedicated to the public domain. Reference: https://www.sqlite.org/copyright.html

## Container image

`Dockerfile` uses the upstream `python:3.12-slim` image. Python and the base image's operating-system packages retain their respective licenses, which can include GPL and LGPL. HACS's Apache-2.0 license applies to HACS files, not to the entire container image. Redistributors must retain required notices and meet applicable source-provision obligations for the components they distribute.

This document is an application-level dependency inventory, not a complete inventory of an image's packages. The base-image tag is mutable. Before distributing a built image, record its digest and inspect the actual installed packages and their copyright/license files (including `/usr/share/doc/*/copyright`).

Official image source and maintenance information: https://github.com/docker-library/python

## Host software and reference documents

Docker Desktop is separately licensed under Docker's subscription agreement; it is not included in HACS. See https://docs.docker.com/subscription-billing/desktop-license/ .

External standards and reference documents linked from the documentation retain the rights and terms of their publishers. Listing a reference does not apply Apache-2.0 to that document or grant rights to third-party names and logos.
