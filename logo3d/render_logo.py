"""Build and render a 3D studio shot of the ELEKTROMIX. logotype.

Usage: python3 render_logo.py --variant hero --res 2560x1100 --samples 400 --out hero.png
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO_WIDTH = 10.0          # scene units across the whole logotype
DEPTH = 0.30               # total extrusion depth
BEVEL = 0.013              # edge bevel width

ORANGE_SRGB = (251 / 255, 97 / 255, 0.0)
GAIN = 1.0                 # global light multiplier, calibrated against the brand orange


def srgb_to_linear(c):
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser()
    p.add_argument('--variant', default='hero', choices=['hero', 'light', 'detail'])
    p.add_argument('--res', default='1280x550')
    p.add_argument('--samples', type=int, default=96)
    p.add_argument('--out', default='render.png')
    p.add_argument('--gain', type=float, default=1.0)
    p.add_argument('--exposure', type=float, default=None)
    p.add_argument('--save-blend', default='')
    return p.parse_args(argv)


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_ink():
    """Import the two traced SVG groups, returning (black_obj, orange_obj)."""
    objs = {}
    for name in ('black', 'orange'):
        before = set(bpy.data.objects)
        bpy.ops.import_curve.svg(filepath=os.path.join(HERE, f'logo_{name}.svg'))
        new = [o for o in set(bpy.data.objects) - before if o.type == 'CURVE']
        if not new:
            raise RuntimeError(f'SVG import produced no curves for {name}')
        # the importer may split a path into several objects; join them
        bpy.ops.object.select_all(action='DESELECT')
        for o in new:
            o.select_set(True)
        bpy.context.view_layer.objects.active = new[0]
        if len(new) > 1:
            bpy.ops.object.join()
        obj = bpy.context.view_layer.objects.active
        obj.name = f'ink_{name}'
        objs[name] = obj
    return objs['black'], objs['orange']


def world_bbox(objects):
    lo = Vector((1e9,) * 3)
    hi = Vector((-1e9,) * 3)
    for o in objects:
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            lo = Vector((min(lo[i], w[i]) for i in range(3)))
            hi = Vector((max(hi[i], w[i]) for i in range(3)))
    return lo, hi


def normalise(objects):
    """Scale to LOGO_WIDTH, stand upright in XZ, sit just above z=0, centred on X.

    2D curves refuse applied rotation/location, so the transforms are only set
    here; solidify() bakes them once the curves have become meshes.
    """
    lo, hi = world_bbox(objects)
    s = LOGO_WIDTH / (hi - lo).x
    for o in objects:
        o.scale = (s, s, s)
        # SVG imports flat in XY; stand it up so it faces -Y
        o.rotation_euler = (math.pi / 2, 0, 0)
    bpy.context.view_layer.update()

    lo, hi = world_bbox(objects)
    mid = (lo + hi) / 2
    for o in objects:
        o.location = (-mid.x, -mid.y, -lo.z + 0.10)
    bpy.context.view_layer.update()
    return world_bbox(objects)


def solidify(obj):
    """Extrude the flat curve, convert to mesh and bevel the edges."""
    cu = obj.data
    cu.dimensions = '2D'
    cu.fill_mode = 'BOTH'
    cu.resolution_u = 16
    cu.extrude = (DEPTH / 2.0) / obj.scale.z   # object scale is baked in below

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.convert(target='MESH')
    # bake the transforms now so the bevel width is in world units
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    bev = obj.modifiers.new('Bevel', 'BEVEL')
    bev.width = BEVEL
    bev.segments = 4
    bev.limit_method = 'ANGLE'
    bev.angle_limit = math.radians(30)
    bev.use_clamp_overlap = True
    bev.harden_normals = False
    bev.miter_outer = 'MITER_ARC'
    bpy.ops.object.shade_smooth()
    bpy.ops.object.modifier_apply(modifier=bev.name)
    bpy.ops.object.shade_auto_smooth(angle=math.radians(28))


def plastic(name, srgb, roughness, coat=0.35, coat_rough=0.06):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    lin = srgb_to_linear(srgb)
    b.inputs['Base Color'].default_value = (*lin, 1.0)
    b.inputs['Roughness'].default_value = roughness
    b.inputs['Metallic'].default_value = 0.0
    for key, val in (('Coat Weight', coat), ('Coat Roughness', coat_rough),
                     ('IOR', 1.5), ('Specular IOR Level', 0.5)):
        if key in b.inputs:
            b.inputs[key].default_value = val
    return m


def area_light(name, loc, target, size, power, color=(1, 1, 1), shape='RECTANGLE',
               size_y=None, spread=180.0):
    d = bpy.data.lights.new(name, 'AREA')
    d.shape = shape
    d.size = size
    if size_y is not None:
        d.size_y = size_y
    d.energy = power * GAIN
    d.color = color
    d.spread = math.radians(spread)   # narrow spread keeps beams off the backdrop
    o = bpy.data.objects.new(name, d)
    bpy.context.collection.objects.link(o)
    o.location = loc
    direction = Vector(target) - Vector(loc)
    o.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    # softboxes light and reflect, but must never appear as blobs in frame
    o.visible_camera = False
    return o


def gradient_world(top, bottom, strength=1.0):
    w = bpy.data.worlds.new('World')
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputWorld')
    bg = nt.nodes.new('ShaderNodeBackground')
    bg.inputs['Strength'].default_value = strength
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[0].color = (*srgb_to_linear(bottom), 1)
    ramp.color_ramp.elements[1].position = 0.65
    ramp.color_ramp.elements[1].color = (*srgb_to_linear(top), 1)
    # Incoming.Z runs +1 looking down to -1 looking up, so remap it inverted to
    # get fac=1 overhead; a raw -1..1 value would clamp to the bottom stop.
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    geo = nt.nodes.new('ShaderNodeNewGeometry')
    mr = nt.nodes.new('ShaderNodeMapRange')
    mr.inputs['From Min'].default_value = 1.0
    mr.inputs['From Max'].default_value = -1.0
    nt.links.new(geo.outputs['Incoming'], sep.inputs['Vector'])
    nt.links.new(sep.outputs['Z'], mr.inputs['Value'])
    nt.links.new(mr.outputs['Result'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], bg.inputs['Color'])
    nt.links.new(bg.outputs['Background'], out.inputs['Surface'])


def add_floor(srgb, roughness):
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, 0))
    floor = bpy.context.active_object
    floor.name = 'floor'
    floor.data.materials.append(plastic('floor', srgb, roughness, coat=0.0))
    return floor


def add_backdrop(srgb, y, height=60, width=200):
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, y, height / 2))
    bd = bpy.context.active_object
    bd.name = 'backdrop'
    bd.scale = (width, 1, height)
    bd.rotation_euler = (math.pi / 2, 0, 0)
    bpy.ops.object.transform_apply(scale=True, rotation=True)
    bd.data.materials.append(plastic('backdrop', srgb, 0.55, coat=0.0))
    return bd


def add_camera(target, yaw, pitch, dist, lens=85.0, shift_y=0.0, shift_x=0.0):
    """Place the camera on an orbit: yaw right of centre, pitch above, aimed at target."""
    d = bpy.data.cameras.new('Camera')
    d.lens = lens
    d.shift_y = shift_y
    d.shift_x = shift_x
    cam = bpy.data.objects.new('Camera', d)
    bpy.context.collection.objects.link(cam)
    ya, pi_ = math.radians(yaw), math.radians(pitch)
    cam.location = (
        target[0] + dist * math.sin(ya) * math.cos(pi_),
        target[1] - dist * math.cos(ya) * math.cos(pi_),
        target[2] + dist * math.sin(pi_),
    )
    cam.rotation_euler = (Vector(target) - cam.location).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.scene.camera = cam
    return cam


def dark_studio(aim):
    """Dark glossy sweep with a pool of light behind the type. Shared by hero/detail."""
    gradient_world((0.33, 0.33, 0.36), (0.05, 0.05, 0.055), strength=0.9)
    # mid-dark floor: dark where unlit, but bright enough to hold the light pool
    add_floor((0.135, 0.135, 0.150), 0.11)
    # broad soft key from upper left
    area_light('key', (-9, -11, 8), (-1.5, 0, 0.6), size=18, size_y=11,
               power=2600, spread=110)
    # long thin strip overhead: draws the specular line along the top bevels
    area_light('strip', (0, -2.6, 5.0), aim, size=30, size_y=0.5,
               power=650, spread=80)
    # grazing panel from the right: lights the extruded side walls
    area_light('edge', (16, -7, 3.6), (-0.5, 0, 0.6), size=10, size_y=6,
               power=700, spread=60, color=(1.0, 0.99, 0.97))
    # cool rim from behind right to separate the ink from the background
    area_light('rim', (8, 9, 4.5), (0.5, 0, 0.6), size=14, size_y=7,
               power=1100, color=(0.94, 0.96, 1.0), spread=110)
    # low warm bounce so the black keeps form on its lower faces
    area_light('bounce', (6.5, -8.5, 0.35), (0.5, 0, 0.5), size=12, size_y=3,
               power=300, color=(1.0, 0.82, 0.62), spread=90)
    # pool aimed straight down at the floor behind the mark: the bright field
    # the black half of the logotype silhouettes against
    px = aim[0] - 2.0
    area_light('pool', (px, 9.5, 9.0), (px, 9.5, 0), size=24, size_y=15,
               power=8600, spread=125)
    # big soft board off-camera left: reads as a sheen gradient reflected in
    # the glossy black front faces without lifting them to grey
    area_light('board', (-15, -15, 3.0), (0, 0, 0.6), size=16, size_y=10,
               power=900, spread=140, color=(0.97, 0.98, 1.0))


def build(variant):
    clear_scene()
    black, orange = import_ink()
    normalise([black, orange])
    for o in (black, orange):
        solidify(o)

    black.data.materials.append(
        plastic('ink_black', (0.058, 0.058, 0.064), 0.14, coat=0.5, coat_rough=0.04))
    orange.data.materials.append(
        plastic('ink_orange', ORANGE_SRGB, 0.24, coat=0.05, coat_rough=0.05))

    aim = (0.0, 0.0, 0.62)
    if variant == 'light':
        # bright studio, closest to how the mark is used on white
        # bright backdrop, but a darker floor/world so white bounce does not
        # wash the saturation out of the ink
        gradient_world((0.82, 0.82, 0.85), (0.46, 0.46, 0.49), strength=0.75)
        add_floor((0.74, 0.74, 0.76), 0.08)
        add_backdrop((0.95, 0.95, 0.96), 28)
        area_light('key', (-9, -11, 8), (-1.5, 0, 0.6), size=18, size_y=11,
                   power=1500, spread=120)
        area_light('strip', (0, -3.0, 5.4), aim, size=30, size_y=0.6,
                   power=420, spread=90)
        # grazes the extruded side walls so the depth reads against the light floor
        area_light('edge', (16, -7, 4.0), (-0.5, 0, 0.6), size=10, size_y=6,
                   power=430, spread=70, color=(1.0, 0.98, 0.95))
        area_light('rim', (6, 9, 4.5), (0.5, 0, 0.6), size=14, size_y=7,
                   power=500, color=(0.95, 0.97, 1.0), spread=100)
        cam = add_camera(aim, yaw=16, pitch=7.0, dist=26.5, lens=85,
                         shift_y=0.02, shift_x=0.012)
        exposure = -0.45
    elif variant == 'detail':
        # three-quarter close-up on the ROMIX seam: shows depth, bevel, both inks
        aim = (1.25, 0.0, 0.62)
        dark_studio(aim)
        cam = add_camera(aim, yaw=30, pitch=7.0, dist=11.0, lens=85, shift_y=0.02)
        exposure = -0.45
    else:  # hero — full logotype on the dark glossy sweep
        dark_studio(aim)
        cam = add_camera(aim, yaw=17, pitch=8.5, dist=27.5, lens=85,
                         shift_y=0.02, shift_x=0.012)
        exposure = -0.45

    return cam, exposure


def configure_render(args, exposure):
    sc = bpy.context.scene
    w, h = (int(x) for x in args.res.lower().split('x'))
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.resolution_percentage = 100
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = args.samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.01
    sc.cycles.max_bounces = 10
    sc.cycles.diffuse_bounces = 4
    sc.cycles.glossy_bounces = 6
    sc.cycles.transmission_bounces = 4
    sc.cycles.caustics_reflective = False
    sc.cycles.caustics_refractive = False
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = 'OPENIMAGEDENOISE'
    sc.cycles.use_light_tree = True
    sc.render.film_transparent = False
    if hasattr(sc.cycles, 'filter_width'):
        sc.cycles.filter_width = 1.4
    # PBR Neutral rolls highlights off to white without the hue shift that made
    # the brand orange read yellow under 'Standard'
    sc.view_settings.view_transform = 'Khronos PBR Neutral'
    sc.view_settings.exposure = exposure
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_depth = '8'
    sc.render.image_settings.compression = 15
    sc.render.filepath = args.out if os.path.isabs(args.out) else os.path.join(HERE, args.out)


def main():
    global GAIN
    args = parse_args()
    GAIN = args.gain
    cam, exposure = build(args.variant)
    if args.exposure is not None:
        exposure = args.exposure
    configure_render(args, exposure)
    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, args.save_blend))
    tri = sum(len(o.data.polygons) for o in bpy.data.objects if o.type == 'MESH')
    print(f'[scene] variant={args.variant} faces={tri} res={args.res} '
          f'samples={args.samples}')
    bpy.ops.render.render(write_still=True)
    print('[done]', bpy.context.scene.render.filepath)


main()
