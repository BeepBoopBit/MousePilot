# Contribute to MousePilot

MousePilot is an independent personal project. Use this guide to prepare a small
change to the code or documentation.

## Request a change

Updates follow the maintainer's needs. There is no fixed release schedule.
Use the repository's Issues tab to report a bug or request a feature.
Describe the problem and the result you need.
You can also fork the repository and submit a pull request.
An issue or pull request does not guarantee a change or acceptance.

Discuss large changes in an issue before you start work.
The maintainer can defer or close a request that does not fit the project.
DCO checks and commit sign-offs are not required.

## Prepare a change

Follow the [development guide](docs/development.md).
Keep each change small enough to review.
Preserve the screenshot coordinate rules and input cleanup rules.
Do not retry input after a connection failure with an unknown result.

Use test data in examples and tests.
Keep device tokens, private profiles, desktop images, and local logs out of a PR.
Use [SECURITY.md](SECURITY.md) for security reports.
Use [SUPPORT.md](SUPPORT.md) for help.

## Check the change

Run the checks that apply to the change.
State which checks passed and which checks you did not run.
Separate automated test results from live Windows or Mac test results.
Do not claim support for a platform or device that you did not test.
Update the affected guide when public behavior changes.
Keep the README short. Put detailed instructions in `docs/`.

## Review AI output and source rights

This project uses AI tools for development.
Review AI output before you submit it.
Check the behavior and the tests.
Do not assume that generated material is original or free of restrictions.
Identify known third-party sources and keep their license notices.
Submit only material that you have the right to contribute.
You remain responsible for the proposed behavior, test evidence, and rights
to the material you submit.
Do not submit device tokens, private profiles, desktop images, or local logs
as model inputs or test data.

The project uses the [MIT license](LICENSE).
Contributors keep their copyright.
This project does not require copyright transfer or a separate contributor agreement.
