# global_progress.py - Custom widget for global progress indicator
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, Gsk, Graphene, GObject, Adw

class TavernGlobalProgress(Gtk.Widget):
    """
    A custom widget that visually mimics Bazaar's global progress button background.
    It takes a `fraction` (0.0 to 1.0) and animates the width of an overlay graphic.
    """
    __gtype_name__ = 'TavernGlobalProgress'

    child = GObject.Property(type=Gtk.Widget)
    active = GObject.Property(type=bool, default=False)
    pending = GObject.Property(type=bool, default=False)
    fraction = GObject.Property(type=float, default=0.0)
    actual_fraction = GObject.Property(type=float, default=0.0)
    transition_progress = GObject.Property(type=float, default=0.0)
    pending_progress = GObject.Property(type=float, default=0.0)
    expand_size = GObject.Property(type=int, default=100)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._draw_widget = Gtk.Fixed()
        self._draw_widget.set_halign(Gtk.Align.FILL)
        self._draw_widget.set_valign(Gtk.Align.FILL)
        self._draw_widget.set_parent(self)

        self._draw_widget.add_css_class("global-progress-bar-fill")

        self.connect('notify::child', self._on_child_changed)
        self.connect('notify::active', self._on_active_changed)
        self.connect('notify::fraction', self._on_fraction_changed)
        self.connect('notify::transition-progress', lambda *args: self.queue_resize())
        self.connect('notify::pending-progress', lambda *args: self.queue_allocate())
        self.connect('notify::actual-fraction', lambda *args: self.queue_allocate())

        # Setup animations
        self._transition_target = Adw.PropertyAnimationTarget.new(self, "transition-progress")
        self._transition_spring_up = Adw.SpringParams.new(0.75, 0.8, 200.0)
        self._transition_spring_down = Adw.SpringParams.new(1.5, 0.1, 100.0)
        self._transition_animation = Adw.SpringAnimation.new(
            self, 0.0, 0.0, self._transition_spring_up, self._transition_target)
        self._transition_animation.set_epsilon(0.00005)

        self._fraction_target = Adw.PropertyAnimationTarget.new(self, "actual-fraction")
        self._fraction_spring = Adw.SpringParams.new(1.0, 0.75, 200.0)
        self._fraction_animation = Adw.SpringAnimation.new(
            self, 0.0, 0.0, self._fraction_spring, self._fraction_target)

    def _on_child_changed(self, obj, pspec):
        if self.child:
            self.child.set_parent(self)

    def _on_active_changed(self, obj, pspec):
        self._transition_animation.set_value_from(self.transition_progress)
        self._transition_animation.set_value_to(1.0 if self.active else 0.0)
        self._transition_animation.set_initial_velocity(self._transition_animation.get_velocity())

        self._transition_animation.set_spring_params(
            self._transition_spring_up if self.active else self._transition_spring_down)

        self._transition_animation.play()

    def _on_fraction_changed(self, obj, pspec):
        fraction = max(0.0, min(1.0, self.fraction))
        if fraction < self.actual_fraction or abs(self.actual_fraction - fraction) < 0.001:
            self._fraction_animation.reset()
            self.actual_fraction = fraction
        else:
            self._fraction_animation.set_value_from(self.actual_fraction)
            self._fraction_animation.set_value_to(fraction)
            self._fraction_animation.set_initial_velocity(self._fraction_animation.get_velocity())
            self._fraction_animation.play()

    def do_measure(self, orientation, for_size):
        minimum = 0
        natural = 0
        min_baseline = -1
        nat_baseline = -1

        if self.child:
            minimum, natural, min_baseline, nat_baseline = self.child.measure(orientation, for_size)

        if orientation == Gtk.Orientation.HORIZONTAL:
            add = int(round(self.transition_progress * self.expand_size))
            minimum += add
            natural += add

        return minimum, natural, min_baseline, nat_baseline

    def do_size_allocate(self, width, height, baseline):
        fraction_width = width * self.actual_fraction

        self._draw_widget.allocate(
            int(fraction_width),
            height,
            baseline,
            Gsk.Transform.new()
        )

        if self.child:
            self.child.allocate(width, height, baseline, None)

    def do_snapshot(self, snapshot):
        width = self.get_width()
        height = self.get_height()

        corner_radius = height * 0.5 * (0.3 * self.transition_progress + 0.2)

        gap = height * 0.1
        inner_radius = max(corner_radius - gap, 0.0)

        # Draw child
        if self.child:
            snapshot.push_opacity(max(0.0, min(1.0, 1.0 - self.transition_progress)))
            self.snapshot_child(self.child, snapshot)
            snapshot.pop()

        color = self.get_color()
        if not color:
            color = Gdk.RGBA()
            color.parse("black")

        # Background clip
        total_bounds = Graphene.Rect().init(0.0, 0.0, width, height)
        total_clip = Gsk.RoundedRect()
        total_clip.init_from_rect(total_bounds, corner_radius)

        snapshot.push_rounded_clip(total_clip)
        snapshot.push_opacity(max(0.0, min(1.0, self.transition_progress)))

        # Background color
        bg_color = Gdk.RGBA()
        bg_color.red = color.red
        bg_color.green = color.green
        bg_color.blue = color.blue
        bg_color.alpha = 0.2
        snapshot.append_color(bg_color, total_bounds)

        # Foreground clip
        fraction_bounds = Graphene.Rect().init(0.0, 0.0, width * max(0.0, min(1.0, self.actual_fraction)), height)
        fraction_clip = Gsk.RoundedRect()
        fraction_clip.init_from_rect(fraction_bounds, inner_radius)

        snapshot.push_rounded_clip(fraction_clip)
        self.snapshot_child(self._draw_widget, snapshot)
        snapshot.pop()

        snapshot.pop()
        snapshot.pop()

    def do_dispose(self):
        if self._draw_widget:
            self._draw_widget.unparent()
            self._draw_widget = None
        if self.child:
            self.child.unparent()
            self.child = None
