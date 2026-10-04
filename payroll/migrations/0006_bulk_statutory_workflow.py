# Generated manually for the run-level statutory assessment workflow.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ("payroll", "0005_employeeobligation_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollrun",
            name="review_revision",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Changes to draft calculation inputs increment this revision for stale review protection.",
            ),
        ),
        migrations.CreateModel(
            name="PayrollStatutoryAssessment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("agency", models.CharField(choices=[("SSS", "SSS"), ("PHILHEALTH", "PhilHealth"), ("PAGIBIG", "Pag-IBIG"), ("WITHHOLDING", "Withholding tax")], max_length=12)),
                ("status", models.CharField(choices=[("PROPOSED", "Proposed"), ("READY", "Ready"), ("NEEDS_REVIEW", "Needs attention"), ("REVIEWED", "Reviewed"), ("SUPERSEDED", "Review again")], db_index=True, default="PROPOSED", max_length=16)),
                ("source_type", models.CharField(choices=[("MANUAL", "Existing manual line"), ("ZERO", "Reviewed zero"), ("EXEMPT", "Reviewed not applicable"), ("OTHER_PERIOD", "Handled in another cutoff"), ("IMPORTED", "Imported reviewed amount"), ("CALCULATED", "Calculated amount")], default="MANUAL", max_length=16)),
                ("employee_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("employer_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("calculation_basis", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ("calculation_snapshot", models.JSONField(blank=True, default=dict)),
                ("source_reference", models.CharField(blank=True, max_length=255)),
                ("review_note", models.CharField(blank=True, max_length=500)),
                ("registration_follow_up", models.CharField(blank=True, max_length=500)),
                ("input_fingerprint", models.CharField(blank=True, max_length=64)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("coverage", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="payroll_assessments", to="payroll.employeestatutorycoverage")),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payroll_statutory_assessments", to="employees.employee")),
                ("employee_line", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="employee_statutory_assessments", to="payroll.payrollline")),
                ("employer_line", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="employer_statutory_assessments", to="payroll.payrollline")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payroll_statutory_assessments", to="organizations.organization")),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="payroll_statutory_assessments_reviewed", to=settings.AUTH_USER_MODEL)),
                ("rule_version", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="payroll_assessments", to="payroll.statutoryruleversion")),
                ("statement", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="statutory_assessments", to="payroll.payrollstatement")),
            ],
            options={
                "ordering": ["employee__last_name", "employee__first_name", "agency", "pk"],
            },
        ),
        migrations.AddConstraint(
            model_name="payrollstatutoryassessment",
            constraint=models.UniqueConstraint(fields=("statement", "agency"), name="payroll_stat_assessment_statement_agency_unique"),
        ),
        migrations.AddConstraint(
            model_name="payrollstatutoryassessment",
            constraint=models.CheckConstraint(check=models.Q(employee_amount__gte=0), name="payroll_stat_assessment_employee_nonneg"),
        ),
        migrations.AddConstraint(
            model_name="payrollstatutoryassessment",
            constraint=models.CheckConstraint(check=models.Q(employer_amount__gte=0), name="payroll_stat_assessment_employer_nonneg"),
        ),
        migrations.AddIndex(
            model_name="payrollstatutoryassessment",
            index=models.Index(fields=["organization", "status", "agency"], name="payroll_stat_assess_q_idx"),
        ),
        migrations.AddIndex(
            model_name="payrollstatutoryassessment",
            index=models.Index(fields=["statement", "status"], name="payroll_stat_assess_stmt_idx"),
        ),
    ]
