"""add classroom materials, lectures, and lecture progress

Revision ID: c1f58a2d9e01
Revises: a8d40d7883d0
Create Date: 2026-10-24 16:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1f58a2d9e01'
down_revision: Union[str, None] = 'a8d40d7883d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'classroom_materials',
        sa.Column('id', sa.String(length=255), primary_key=True),
        sa.Column('classroomId', sa.String(length=255), sa.ForeignKey('classrooms.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.Text(), nullable=False, server_default=''),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('filename', sa.Text(), nullable=False, server_default=''),
        sa.Column('fileType', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('fileSize', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('storagePath', sa.Text(), nullable=False),
        sa.Column('uploadedBy', sa.String(length=255), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updatedAt', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_materials_class_created', 'classroom_materials', ['classroomId', 'createdAt'])

    op.create_table(
        'classroom_lectures',
        sa.Column('id', sa.String(length=255), primary_key=True),
        sa.Column('classroomId', sa.String(length=255), sa.ForeignKey('classrooms.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.Text(), nullable=False, server_default=''),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('videoUrl', sa.Text(), nullable=False),
        sa.Column('platform', sa.String(length=40), nullable=False, server_default='other'),
        sa.Column('embedUrl', sa.Text(), nullable=False, server_default=''),
        sa.Column('durationSeconds', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('completionThreshold', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('trackingSupported', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('createdBy', sa.String(length=255), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updatedAt', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_lectures_class_position', 'classroom_lectures', ['classroomId', 'position'])
    op.create_index('ix_lectures_class_created', 'classroom_lectures', ['classroomId', 'createdAt'])

    op.create_table(
        'classroom_lecture_progress',
        sa.Column('id', sa.String(length=255), primary_key=True),
        sa.Column('classroomId', sa.String(length=255), sa.ForeignKey('classrooms.id', ondelete='CASCADE'), nullable=False),
        sa.Column('lectureId', sa.String(length=255), sa.ForeignKey('classroom_lectures.id', ondelete='CASCADE'), nullable=False),
        sa.Column('studentId', sa.String(length=255), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('watchedSeconds', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('lastPositionSeconds', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('totalDurationSeconds', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('watchPercent', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('completed', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('completedAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updatedAt', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('lectureId', 'studentId', name='uq_lecture_student_progress'),
    )
    op.create_index('ix_lecture_progress_class_student', 'classroom_lecture_progress', ['classroomId', 'studentId'])
    op.create_index('ix_lecture_progress_lecture', 'classroom_lecture_progress', ['lectureId'])


def downgrade() -> None:
    op.drop_table('classroom_lecture_progress')
    op.drop_table('classroom_lectures')
    op.drop_table('classroom_materials')
