# SPDX-License-Identifier: GPL-3.0-or-later
bl_info = {
    "name": "Bake Tool",
    "author": "jobjohn",
    "version": (1, 5, 0),
    "blender": (3, 0, 0),
    "location": "3Dビュー > サイドバー(N) > Bake",
    "description": "ハイポリ→ローポリのノーマル/カラーをワンボタンでベイクし .blend と同じフォルダに保存",
    "category": "Object",
}

import os
import bpy

BAKE_SAMPLES = 16  # ノーマル/カラーは少ないサンプルで十分。既定の数千サンプルだと遅すぎる


def missing_material_uv(obj):
    return not any(s.material for s in obj.material_slots) or not obj.data.uv_layers


def add_material_uv(context, obj):
    """無いものだけ足す: マテリアルは新規作成、UV はスマートUV投影"""
    if not any(s.material for s in obj.material_slots):
        m = bpy.data.materials.new(obj.name + "_mat")
        m.use_nodes = True
        if obj.material_slots:
            for s in obj.material_slots:
                s.material = m
        else:
            obj.data.materials.append(m)
    if obj.data.uv_layers:
        return
    sel, active = list(context.selected_objects), context.view_layer.objects.active
    for o in sel:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(island_margin=0.02)
    bpy.ops.object.mode_set(mode='OBJECT')
    obj.select_set(False)
    for o in sel:
        o.select_set(True)
    context.view_layer.objects.active = active


def auto_extrusion(src, dst):
    """ハイポリがローポリからはみ出す量（バウンディングボックスの差）＋余裕"""
    if not src:
        return 0.0
    over = max((s - d) / 2 for s, d in zip(src.dimensions, dst.dimensions))
    return max(0.02, over * 1.5 + 0.01)


def connect(mat, img_node, tag, bake_type):
    """ベイクした画像ノードをプリンシプルBSDFにつなぐ（ノーマルはノーマルマップノード経由）"""
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    img_node.name = img_node.label = tag
    bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if not bsdf:
        return
    if bake_type == 'NORMAL':
        img_node.location = bsdf.location.x - 550, bsdf.location.y - 400
        nm = nodes.new('ShaderNodeNormalMap')
        nm.name = nm.label = tag + "_map"
        nm.location = bsdf.location.x - 250, bsdf.location.y - 400
        links.new(img_node.outputs['Color'], nm.inputs['Color'])
        links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
    else:
        img_node.location = bsdf.location.x - 350, bsdf.location.y
        links.new(img_node.outputs['Color'], bsdf.inputs['Base Color'])


def bake(op, context, bake_type):
    s = context.scene.bake_tool
    src, dst = s.src, s.dst
    if not bpy.data.filepath:
        op.report({'ERROR'}, "先に .blend を保存してください")
        return {'CANCELLED'}
    if not dst or dst.type != 'MESH':
        op.report({'ERROR'}, "dst（ローポリ）のメッシュを選んでください")
        return {'CANCELLED'}
    if src and (src == dst or src.type != 'MESH'):
        op.report({'ERROR'}, "src（ハイポリ）には dst と別のメッシュを選んでください")
        return {'CANCELLED'}
    for o in (src, dst):
        if o and not o.visible_get():
            op.report({'ERROR'}, f"{o.name} が非表示です。表示してから実行してください")
            return {'CANCELLED'}
    if s.auto_setup:
        add_material_uv(context, dst)
    mats = {s.material for s in dst.material_slots if s.material}
    if not mats or not dst.data.uv_layers:
        op.report({'ERROR'}, f"{dst.name} にマテリアルとUVが必要です")
        return {'CANCELLED'}

    scene = context.scene
    size = s.size
    suffix = 'normal' if bake_type == 'NORMAL' else 'color'
    name = f"{dst.name}_{suffix}"
    img = bpy.data.images.get(name)
    if img:
        img.scale(size, size)
    else:
        img = bpy.data.images.new(name, size, size)
    img.colorspace_settings.name = 'Non-Color' if bake_type == 'NORMAL' else 'sRGB'

    prev = (scene.render.engine, scene.cycles.samples, list(context.selected_objects), context.view_layer.objects.active)
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = BAKE_SAMPLES
    # ベイク先にするため dst の各マテリアルに画像ノードを追加してアクティブにする。
    # 前回このツールがつないだノードは先に消す（つないだままだと単体ベイクで自分自身を読んでしまう）
    tag = "BakeTool_" + suffix
    temp = []
    for m in mats:
        m.use_nodes = True
        nodes = m.node_tree.nodes
        for old in (tag, tag + "_map"):
            if old in nodes:
                nodes.remove(nodes[old])
        n = nodes.new('ShaderNodeTexImage')
        n.image = img
        nodes.active = n
        temp.append((m, n))
    ok = False
    try:
        for o in context.selected_objects:
            o.select_set(False)
        if src:
            src.select_set(True)
        dst.select_set(True)
        context.view_layer.objects.active = dst
        kw = dict(use_clear=True, use_selected_to_active=bool(src), cage_extrusion=s.extrusion or auto_extrusion(src, dst))
        if bake_type == 'DIFFUSE':
            kw["pass_filter"] = {'COLOR'}
        bpy.ops.object.bake(type=bake_type, **kw)
        ok = True
    except RuntimeError as e:
        op.report({'ERROR'}, str(e))
        return {'CANCELLED'}
    finally:
        for m, n in temp:
            if ok:
                connect(m, n, tag, bake_type)
            else:
                m.node_tree.nodes.remove(n)
        scene.render.engine, scene.cycles.samples, sel, active = prev
        for o in context.selected_objects:
            o.select_set(False)
        for o in sel:
            o.select_set(True)
        context.view_layer.objects.active = active

    img.filepath_raw = os.path.join(os.path.dirname(bpy.data.filepath), name + ".png")
    img.file_format = 'PNG'
    img.save()
    op.report({'INFO'}, f"保存: {name}.png")
    return {'FINISHED'}


def is_mesh(self, obj):
    return obj.type == 'MESH'


class BakeSettings(bpy.types.PropertyGroup):
    """シーンに保存するので、ダイアログを閉じても .blend を開き直しても前回の値が残る"""
    src: bpy.props.PointerProperty(type=bpy.types.Object, poll=is_mesh, name="src（ハイポリ）",
                                   description="ベイク元。空なら dst 自身をベイク")
    dst: bpy.props.PointerProperty(type=bpy.types.Object, poll=is_mesh, name="dst（ローポリ）",
                                   description="ベイク先。テクスチャはこのオブジェクトのUVに書き込まれる")
    extrusion: bpy.props.FloatProperty(
        name="押し出し距離（0=自動）", default=0.0, min=0.0, soft_max=1.0, unit='LENGTH',
        description="dst の表面を外側に膨らませてから src に向けてレイを飛ばす距離。ハイポリが外にはみ出す分より大きくする",
    )
    auto_setup: bpy.props.BoolProperty(
        name="マテリアルとUVを自動で設定する", default=True,
        description="dst にマテリアルやUVが無ければ、新しいマテリアルを作りスマートUV投影でUVを作る",
    )
    size: bpy.props.IntProperty(name="解像度", default=2048, min=64, max=16384)


class BakeDialog:
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def invoke(self, context, event):
        # dst が未設定のときだけ選択から埋める（アクティブ=dst / もう片方=src）。設定済みなら前回の値をそのまま使う
        s = context.scene.bake_tool
        active = context.view_layer.objects.active
        if not s.dst and active and active.type == 'MESH':
            s.dst = active
            others = [o for o in context.selected_objects if o.type == 'MESH' and o != active]
            s.src = others[0] if others else None
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        s = context.scene.bake_tool
        col = self.layout.column()
        col.prop(s, "src", icon='MESH_DATA')
        col.prop(s, "dst", icon='MESH_DATA')
        if s.dst and missing_material_uv(s.dst):
            box = col.box()
            box.label(text=f"{s.dst.name} にマテリアルかUVがありません", icon='ERROR')
            box.prop(s, "auto_setup")
        col.prop(s, "extrusion")
        col.prop(s, "size")

    def execute(self, context):
        return bake(self, context, self.bake_type)


class BAKETOOL_OT_normal(BakeDialog, bpy.types.Operator):
    bl_idname = "bake_tool.normal"
    bl_label = "ノーマルをベイク"
    bl_description = "src（ハイポリ）のノーマルを dst（ローポリ）にベイクし、.blend と同じフォルダに PNG で保存"
    bake_type = 'NORMAL'


class BAKETOOL_OT_color(BakeDialog, bpy.types.Operator):
    bl_idname = "bake_tool.color"
    bl_label = "カラーをベイク"
    bl_description = "src（ハイポリ）のベースカラーを dst（ローポリ）にベイクし、.blend と同じフォルダに PNG で保存"
    bake_type = 'DIFFUSE'


class BAKETOOL_PT_panel(bpy.types.Panel):
    bl_label = "Bake Tool"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Bake"

    def draw(self, context):
        col = self.layout.column()
        col.prop(context.scene.bake_tool, "size")
        col.operator(BAKETOOL_OT_normal.bl_idname, icon='NORMALS_FACE')
        col.operator(BAKETOOL_OT_color.bl_idname, icon='COLOR')
        if context.mode != 'OBJECT':
            col.label(text="オブジェクトモードにしてください", icon='ERROR')
        if not bpy.data.filepath:
            col.label(text=".blend を保存すると使えます", icon='ERROR')


classes = (BakeSettings, BAKETOOL_OT_normal, BAKETOOL_OT_color, BAKETOOL_PT_panel)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.bake_tool = bpy.props.PointerProperty(type=BakeSettings)


def unregister():
    del bpy.types.Scene.bake_tool
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
