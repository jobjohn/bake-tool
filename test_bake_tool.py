import bpy, os, sys
# 実行: Blender -b --python test_bake_tool.py -- <空の作業フォルダ>
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_tool; bake_tool.register()
S = sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)

# high: 赤いマテリアルのサブディビ済みスザンヌ
bpy.ops.mesh.primitive_monkey_add()
high = bpy.context.active_object; high.name = "High"
mod = high.modifiers.new("s", 'SUBSURF'); mod.levels = 2
red = bpy.data.materials.new("Red"); red.use_nodes = True
red.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (1, 0, 0, 1)
high.data.materials.append(red)

# low: UV と白いマテリアルを持つスザンヌ
bpy.ops.mesh.primitive_monkey_add()
low = bpy.context.active_object; low.name = "Low"
m = bpy.data.materials.new("M"); m.use_nodes = True
low.data.materials.append(m)
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.uv.smart_project(); bpy.ops.object.mode_set(mode='OBJECT')

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(S, "t.blend"))
s = bpy.context.scene.bake_tool
s.size = 256


def run(op, src, dst, **kw):
    """ダイアログで値を選んで OK を押したのと同じ: シーンの設定を書いて実行"""
    s.src, s.dst = bpy.data.objects.get(src), bpy.data.objects[dst]
    for k, v in kw.items():
        setattr(s, k, v)
    return op('EXEC_DEFAULT')


assert run(bpy.ops.bake_tool.normal, src="High", dst="Low") == {'FINISHED'}
assert run(bpy.ops.bake_tool.color, src="High", dst="Low") == {'FINISHED'}
assert run(bpy.ops.bake_tool.color, src="", dst="Low") == {'FINISHED'}  # src 空なら単体ベイク
for n in ("Low_normal.png", "Low_color.png"):
    assert os.path.exists(os.path.join(S, n)), n

# high→low のカラーで dst の白ではなく src の赤が乗ることを確認
run(bpy.ops.bake_tool.color, src="High", dst="Low")
px = list(bpy.data.images.load(os.path.join(S, "Low_color.png"), check_existing=False).pixels)
assert max(px[0::4]) > 0.9 and max(px[1::4]) < 0.1, "src の色が乗っていない"
# ベイク結果がマテリアルにつながっていて、何度ベイクしてもノードが増えない
nodes = m.node_tree.nodes
bsdf = nodes["Principled BSDF"]
assert sorted(nodes.keys()) == sorted(["Principled BSDF", "Material Output", "BakeTool_normal", "BakeTool_normal_map", "BakeTool_color"]), nodes.keys()
assert bsdf.inputs["Base Color"].links[0].from_node.name == "BakeTool_color"
assert bsdf.inputs["Normal"].links[0].from_node.name == "BakeTool_normal_map"
try:
    run(bpy.ops.bake_tool.normal, src="Low", dst="Low")
    raise AssertionError("src==dst が通ってしまった")
except RuntimeError:
    pass
# マテリアルもUVも無い立方体: 自動設定オフなら止まり、オンなら設定してベイクできる
bpy.ops.mesh.primitive_cube_add()
cube = bpy.context.active_object; cube.name = "Cube"
cube.data.uv_layers.remove(cube.data.uv_layers[0])
assert bake_tool.missing_material_uv(cube)
try:
    run(bpy.ops.bake_tool.normal, src="High", dst="Cube", auto_setup=False)
    raise AssertionError("自動設定オフなのに通ってしまった")
except RuntimeError:
    pass
assert run(bpy.ops.bake_tool.normal, src="High", dst="Cube", auto_setup=True) == {'FINISHED'}
assert not bake_tool.missing_material_uv(cube)
assert bpy.context.mode == 'OBJECT'
# 設定はシーンに残る（次にダイアログを開いたとき前回の値が出る）
assert s.src.name == "High" and s.dst.name == "Cube" and s.auto_setup is True
print("ALL OK")
