"""Thai text for the PDF calculation report (``lang="th"``).

Keys are the English strings used in ``report.py``; a missing key falls back to English, so a new English line never
breaks the report. Numbers, clause numbers, member ids and the design modules' notes stay as calculated (English).
"""
from __future__ import annotations

import re

TH: dict[str, str] = {
    # tags and statuses
    "INPUT": "ข้อมูลที่กำหนด",
    "ASSUMED": "ค่าสมมติ",
    "CALCULATED": "ผลการคำนวณ",
    "OK": "ผ่าน",
    "OVER 1.0": "เกิน 1.0",
    "NOT COVERED": "ไม่ครอบคลุม",
    "skipped": "ข้าม",
    "CHECK": "ตรวจสอบ",
    # title block
    "Structural model": "แบบจำลองโครงสร้าง",
    "Calculation report: 3D linear analysis": "รายการคำนวณ: การวิเคราะห์โครงสร้างเชิงเส้น 3 มิติ",
    "Calculation report: 3D linear analysis and member design":
        "รายการคำนวณ: การวิเคราะห์โครงสร้างเชิงเส้น 3 มิติ และการออกแบบองค์อาคาร",
    "Project": "โครงการ",
    "Engineer": "วิศวกร",
    "Date": "วันที่",
    "Design standard (loads)": "มาตรฐาน (น้ำหนักบรรทุก)",
    "EN 1990 (Eurocode)": "EN 1990 (Eurocode)",
    "ASCE 7": "ASCE 7",
    "Thai (DPT / EIT)": "มาตรฐานไทย (มยผ. / วสท.)",
    "Units": "หน่วย",
    "kN, m (forces kN, moments kN·m, displacements mm where noted)":
        "kN, m (แรง kN, โมเมนต์ kN·m, การเคลื่อนตัว mm ตามที่ระบุ)",
    "Software": "โปรแกรม",
    "Structural Analyze (open source); report generated from the model at the time of printing":
        "Structural Analyze (โอเพนซอร์ส) สร้างรายการคำนวณจากแบบจำลอง ณ เวลาที่พิมพ์",
    "SCOPE":
        "<b>ขอบเขตของรายการคำนวณ</b> ผลทุกรายการด้านล่างคำนวณโดยโปรแกรมจากแบบจำลองที่แสดง ณ เวลาที่พิมพ์ "
        "ป้ายกำกับ: {INPUT} กำหนดโดยผู้ใช้หรือโดยตัวสร้างแบบจำลอง; {ASSUMED} ค่าเริ่มต้นหรือการประมาณที่โปรแกรมเลือก; "
        "{CALCULATED} ค่าที่คำนวณได้ อัตราส่วนการใช้งาน (utilisation) ไม่เกิน 1.0 หมายความว่าองค์อาคารผ่านรายการตรวจสอบ"
        "ที่ระบุไว้เท่านั้น รายการคำนวณนี้<b>ไม่ใช่</b>การรับรองว่าโครงสร้างปลอดภัยหรือเป็นไปตามมาตรฐาน: รอยต่อ ฐานราก "
        "เสถียรภาพโดยรวม สภาวะใช้งาน รายละเอียดการเสริมเหล็ก และรายการในหมายเหตุ ต้องได้รับการตรวจสอบแยกต่างหาก"
        "โดยวิศวกรผู้มีคุณสมบัติ",
    "LANG_NOTE":
        "ชื่อหัวข้อและชื่อรายการตรวจสอบแสดงเป็นภาษาไทย ส่วนเลขข้อกำหนด หมายเหตุการออกแบบ และข้อความจากตัววิเคราะห์ "
        "แสดงเป็นภาษาอังกฤษตามที่โปรแกรมคำนวณ",
    "3D view of the model as shown on screen when the report was printed (illustration, not a result).":
        "ภาพ 3 มิติของแบบจำลองตามที่แสดงบนหน้าจอขณะพิมพ์ (ภาพประกอบ ไม่ใช่ผลการคำนวณ)",
    "Steel design could not run: {e}": "ไม่สามารถออกแบบองค์อาคารเหล็กได้: {e}",
    "RC design could not run: {e}": "ไม่สามารถออกแบบคอนกรีตเสริมเหล็กได้: {e}",
    "Buckling analysis could not run for {load}: {e}": "ไม่สามารถวิเคราะห์การโก่งเดาะสำหรับ {load} ได้: {e}",
    # model
    "Model": "แบบจำลอง",
    "Item": "รายการ",
    "Value": "ค่า",
    "Nodes": "จุดต่อ",
    "Members": "องค์อาคาร",
    "Slab panels": "แผ่นพื้น",
    "Wall panels": "ผนัง",
    "Supports": "จุดรองรับ",
    "Load cases": "กรณีน้ำหนักบรรทุก",
    "Combinations": "การรวมน้ำหนักบรรทุก",
    "Extent X × Y × Z (m)": "ขนาดโดยรวม X × Y × Z (m)",
    "Model source: {g} generator.": "ที่มาของแบบจำลอง: ตัวสร้างแบบจำลอง {g}",
    "Materials": "วัสดุ",
    "Id": "รหัส",
    "Name": "ชื่อ",
    "Kind": "ชนิด",
    "Density (kN/m³)": "หน่วยน้ำหนัก (kN/m³)",
    "steel": "เหล็ก",
    "concrete": "คอนกรีต",
    "Sections": "หน้าตัด",
    "Shape": "รูปร่าง",
    "Material": "วัสดุ",
    "fixed": "ยึดแน่น",
    "pinned": "ยึดหมุน",
    "roller": "ล้อเลื่อน",
    "restrained": "ยึดรั้ง",
    "No supports.": "ไม่มีจุดรองรับ",
    "Model notes": "หมายเหตุของแบบจำลอง",
    # loads
    "Loads": "น้ำหนักบรรทุก",
    "Type": "ประเภท",
    "Self-weight": "น้ำหนักตัวเอง",
    "Loads defined": "จำนวนน้ำหนักที่กำหนด",
    "yes": "มี",
    "Load combinations": "การรวมน้ำหนักบรรทุก",
    "Factors": "ตัวคูณ",
    "Used for design": "ใช้ในการออกแบบ",
    "no (serviceability)": "ไม่ใช้ (สภาวะใช้งาน)",
    "Combinations whose id or name contains sls, serv, service, characteristic or ths are treated as serviceability "
    "combinations and are not used for member design.":
        "การรวมน้ำหนักที่รหัสหรือชื่อมีคำว่า sls, serv, service, characteristic หรือ ths ถือเป็นการรวมน้ำหนัก"
        "สำหรับสภาวะใช้งาน และไม่ใช้ในการออกแบบองค์อาคาร",
    # analysis
    "Linear static analysis": "การวิเคราะห์สถิตเชิงเส้น",
    "Analysis assumptions": "สมมติฐานการวิเคราะห์",
    "Linear elastic material, small displacements (first-order analysis) unless P-Delta is listed below.":
        "วัสดุยืดหยุ่นเชิงเส้น การเคลื่อนตัวน้อย (การวิเคราะห์อันดับหนึ่ง) ยกเว้นกรณี P-Delta ที่ระบุด้านล่าง",
    "Members are straight Euler-Bernoulli beam elements; member end releases as defined.":
        "องค์อาคารเป็นชิ้นส่วนคานตรงแบบ Euler-Bernoulli และปลดแรงที่ปลายองค์อาคารตามที่กำหนด",
    "Slab area loads are distributed to the supporting beams by tributary areas; slabs are not FE-analysed.":
        "น้ำหนักแผ่บนแผ่นพื้นถ่ายลงคานรองรับตามพื้นที่รับน้ำหนัก (tributary area) ไม่ได้วิเคราะห์แผ่นพื้นด้วยไฟไนต์เอลิเมนต์",
    "Solver messages": "ข้อความจากตัววิเคราะห์",
    "Equilibrium check (sum of applied loads vs sum of reactions)":
        "การตรวจสอบสมดุล (ผลรวมน้ำหนักที่กระทำเทียบกับผลรวมแรงปฏิกิริยา)",
    "Load case": "กรณีน้ำหนัก",
    "Sum Fx applied": "ผลรวม Fx กระทำ",
    "Sum Fy applied": "ผลรวม Fy กระทำ",
    "Sum Fz applied": "ผลรวม Fz กระทำ",
    "Sum Fz reactions": "ผลรวม Fz ปฏิกิริยา",
    "Force error": "คลาดเคลื่อน แรง",
    "Moment error": "คลาดเคลื่อน โมเมนต์",
    "Check": "ผล",
    "Errors are relative to the applied load; values near machine precision mean the solution is in equilibrium.":
        "ความคลาดเคลื่อนเทียบกับน้ำหนักที่กระทำ ค่าที่ใกล้ความละเอียดของการคำนวณแสดงว่าผลลัพธ์อยู่ในสมดุล",
    "Support reactions per load case (kN, kN·m)": "แรงปฏิกิริยาที่จุดรองรับแยกตามกรณีน้ำหนัก (kN, kN·m)",
    "Node": "จุดต่อ",
    "Sum": "ผลรวม",
    "Reactions for a combination are the sums of the load-case reactions above multiplied by the combination factors "
    "(linear analysis).":
        "แรงปฏิกิริยาของการรวมน้ำหนัก เท่ากับผลรวมของแรงปฏิกิริยาแต่ละกรณีข้างต้นคูณด้วยตัวคูณของการรวมน้ำหนัก "
        "(การวิเคราะห์เชิงเส้น)",
    "Extreme member internal forces per load (kN, kN·m)": "แรงภายในสูงสุดขององค์อาคารแยกตามน้ำหนัก (kN, kN·m)",
    "Local axes: N axial (tension positive), Vy / Vz shear, T torsion, My / Mz bending about the local y / z axes. "
    "Values are taken at the member stations (ends, intermediate points).":
        "แกนเฉพาะที่: N แรงตามแนวแกน (แรงดึงเป็นบวก), Vy / Vz แรงเฉือน, T แรงบิด, My / Mz โมเมนต์ดัดรอบแกน y / z "
        "เฉพาะที่ ค่าอ่านที่ตำแหน่งสถานีขององค์อาคาร (ปลายและจุดภายใน)",
    "Load": "น้ำหนัก",
    "Force": "แรง",
    "Max": "สูงสุด",
    "Min": "ต่ำสุด",
    "Member @ x (m)": "องค์อาคาร @ x (m)",
    "Member force envelope over all combinations (largest absolute values, kN, kN·m)":
        "ขอบเขตแรงภายในองค์อาคารจากทุกการรวมน้ำหนัก (ค่าสัมบูรณ์สูงสุด, kN, kN·m)",
    "Member": "องค์อาคาร",
    "Section": "หน้าตัด",
    "Governing load (|M| max)": "น้ำหนักวิกฤต (|M| สูงสุด)",
    "Only the first {n} of {m} members are listed.": "แสดงเฉพาะ {n} องค์อาคารแรกจากทั้งหมด {m} องค์อาคาร",
    # stability
    "Elastic critical buckling": "การโก่งเดาะวิกฤตแบบยืดหยุ่น",
    "Load: <b>{load}</b> {name}.": "น้ำหนัก: <b>{load}</b> {name}",
    "Mode": "โหมด",
    "Critical load factor alpha_cr": "ตัวคูณน้ำหนักวิกฤต alpha_cr",
    "BUCKLING_REF":
        "ค่า alpha_cr ต่ำสุด = {a}. เพื่อการอ้างอิง EN 1993-1-1 ข้อ 5.2.1(3) อนุญาตให้ใช้การวิเคราะห์อันดับหนึ่งเมื่อ "
        "alpha_cr >= 10; AISC 360 ภาคผนวก 7 / บท C ใช้อัตราส่วนการเคลื่อนตัวด้านข้างอันดับสองต่ออันดับหนึ่งแทน "
        "โปรแกรมไม่ได้ตัดสินว่าโครงการของท่านต้องใช้การวิเคราะห์แบบใด",
    # design
    "Steel member design: {code}": "การออกแบบองค์อาคารเหล็ก: {code}",
    "Reinforced concrete design: {code}": "การออกแบบคอนกรีตเสริมเหล็ก: {code}",
    "Util.": "อัตราส่วน",
    "Governing check": "รายการวิกฤต",
    "Governing": "รายการวิกฤต",
    "Clause": "ข้อ",
    "Combo": "การรวม",
    "Status": "สถานะ",
    "RC_OPTIONS": "เหล็กยืน {main} เหล็กปลอก {tie} ระยะหุ้มสุทธิ {cover} cm เหล็กปลอกขนาด {stirrup}",
    "Beams": "คาน",
    "Bottom": "เหล็กล่าง",
    "Top": "เหล็กบน",
    "Stirrups": "เหล็กปลอก",
    "Side bars": "เหล็กข้าง",
    "Columns": "เสา",
    "Bars": "เหล็กยืน",
    "Layout": "การจัดเหล็ก",
    "Ties": "เหล็กปลอก",
    "Checked": "ตรวจสอบ",
    "Over 1.0": "เกิน 1.0",
    "Not covered": "ไม่ครอบคลุม",
    "Skipped": "ข้าม",
    "Max utilisation": "อัตราส่วนสูงสุด",
    "Combinations used: {c}.": "การรวมน้ำหนักที่ใช้: {c}",
    "Check details: most utilised members": "รายละเอียดการตรวจสอบ: องค์อาคารที่มีอัตราส่วนการใช้งานสูงสุด",
    "Check details: most utilised members and members over 1.0":
        "รายละเอียดการตรวจสอบ: องค์อาคารที่มีอัตราส่วนการใช้งานสูงสุด และองค์อาคารที่เกิน 1.0",
    "Demand": "ค่าที่เกิดขึ้น",
    "Capacity": "กำลังต้านทาน",
    "Unit": "หน่วย",
    "Ratio": "อัตราส่วน",
    "Check ": "รายการตรวจสอบ",
    "MEMBER_HEAD": "<b>{id}</b> {sec}: อัตราส่วนการใช้งาน <b>{u}</b> ({status})",
    "Not covered ({n}): outside the implemented clauses, check by hand":
        "ไม่ครอบคลุม ({n}): อยู่นอกข้อกำหนดที่โปรแกรมรองรับ ต้องตรวจสอบด้วยมือ",
    "… and {n} more.": "… และอีก {n} รายการ",
    "Design notes and assumptions": "หมายเหตุและสมมติฐานการออกแบบ",
    "({k} members)": "({k} องค์อาคาร)",
    "({k} member)": "({k} องค์อาคาร)",
    # closing
    "Limitations": "ข้อจำกัด",
    "The analysis is linear elastic. Second-order effects are included only where a P-Delta load is listed.":
        "การวิเคราะห์เป็นแบบยืดหยุ่นเชิงเส้น ผลอันดับสองรวมไว้เฉพาะกรณีที่ระบุน้ำหนัก P-Delta",
    "Member design covers only the checks listed in the tables; members marked NOT COVERED or skipped must be checked by hand.":
        "การออกแบบองค์อาคารครอบคลุมเฉพาะรายการตรวจสอบในตาราง องค์อาคารที่ระบุว่าไม่ครอบคลุมหรือข้าม ต้องตรวจสอบด้วยมือ",
    "Connections, base plates, foundations, punching shear, slabs, walls, fatigue, fire, serviceability limits "
    "(deflection, vibration) and detailing (anchorage, laps, curtailment) are not checked by this report.":
        "รายการคำนวณนี้ไม่ได้ตรวจสอบรอยต่อ แผ่นฐาน ฐานราก แรงเฉือนทะลุ แผ่นพื้น ผนัง ความล้า อัคคีภัย สภาวะใช้งาน "
        "(การแอ่นตัว การสั่นสะเทือน) และรายละเอียดการเสริมเหล็ก (ระยะฝัง ระยะทาบ การตัดเหล็ก)",
    "Default sections, effective lengths and supports chosen by a generator or by the DXF import are assumptions: "
    "replace them with the project values before relying on the results.":
        "หน้าตัด ความยาวประสิทธิผล และจุดรองรับที่เป็นค่าเริ่มต้นจากตัวสร้างแบบจำลองหรือการนำเข้า DXF เป็นค่าสมมติ "
        "ต้องแทนด้วยค่าของโครงการก่อนนำผลไปใช้",
    "This report does not state that the structure is safe or code-compliant.":
        "รายการคำนวณนี้ไม่ได้รับรองว่าโครงสร้างปลอดภัยหรือเป็นไปตามมาตรฐาน",
    # page furniture
    "{title}: calculation report": "{title}: รายการคำนวณ",
    "Structural Analyze. Results are calculated; see section labels and limitations.":
        "Structural Analyze ผลลัพธ์ได้จากการคำนวณ ดูป้ายกำกับในแต่ละหัวข้อและข้อจำกัด",
    "Page {n}": "หน้า {n}",
}

# Phrases of the design modules' check names, longest first so whole names win over their parts.
_CHECK_PHRASES = sorted({
    "Axial + biaxial bending (P-M, load contour)": "แรงตามแนวแกนร่วมกับโมเมนต์ดัดสองแกน (P-M, load contour)",
    "Biaxial bending with LTB (axial tension neglected)": "โมเมนต์ดัดสองแกนร่วมกับการโก่งเดาะทางข้าง (ไม่คิดแรงดึง)",
    "Axial + bending interaction": "ผลร่วมแรงตามแนวแกนและโมเมนต์ดัด",
    "Cross-section: bending + axial + shear": "หน้าตัด: โมเมนต์ดัด + แรงตามแนวแกน + แรงเฉือน",
    "Shear + torsion: section size": "แรงเฉือน + แรงบิด: ขนาดหน้าตัด",
    "Torsion longitudinal steel Al": "เหล็กยืนรับแรงบิด Al",
    "Flexure, negative (top bars)": "โมเมนต์ลบ (เหล็กบน)",
    "Flexure, positive (bottom bars)": "โมเมนต์บวก (เหล็กล่าง)",
    "Steel ratio negative (top bars)": "อัตราส่วนเหล็กเสริม โมเมนต์ลบ (เหล็กบน)",
    "Steel ratio positive (bottom bars)": "อัตราส่วนเหล็กเสริม โมเมนต์บวก (เหล็กล่าง)",
    "Buckling interaction": "ผลร่วมการโก่งเดาะ",
    "Annex B": "ภาคผนวก B",
    "Compression resistance": "กำลังรับแรงอัดของหน้าตัด",
    "Axial compression": "แรงอัดตามแนวแกน",
    "Flexural buckling": "การโก่งเดาะดัด",
    "Lateral-torsional buckling": "การโก่งเดาะทางข้าง",
    "lateral-torsional buckling": "การโก่งเดาะทางข้าง",
    "flexural-torsional": "การโก่งเดาะดัด-บิด",
    "flange local buckling": "การโก่งเดาะเฉพาะที่ของปีก",
    "local buckling": "การโก่งเดาะเฉพาะที่",
    "Major-axis bending": "โมเมนต์ดัดรอบแกนหลัก",
    "Minor-axis bending": "โมเมนต์ดัดรอบแกนรอง",
    "major axis": "แกนหลัก",
    "minor axis": "แกนรอง",
    "torsional": "การโก่งเดาะบิด",
    "flexural": "การโก่งเดาะดัด",
    "yielding": "การคราก",
    "Compression": "แรงอัด",
    "gross yielding": "การครากของหน้าตัดทั้งหมด",
    "gross section": "หน้าตัดทั้งหมด",
    "vertical stirrups": "เหล็กปลอกแนวดิ่ง",
    "closed stirrups": "เหล็กปลอกปิด",
    "Tension": "แรงดึง",
    "Torsion": "แรงบิด",
    "Shear": "แรงเฉือน",
}.items(), key=lambda kv: -len(kv[0]))
_LEGS = re.compile(r"\(ties, (\d+) legs\)")


def check_name_th(name: str) -> str:
    """Thai name of a design check; unknown words stay in English."""
    s = _LEGS.sub(r"(เหล็กปลอกเสา \1 ขา)", name)
    for en, th in _CHECK_PHRASES:
        s = s.replace(en, th)
    return s


_REBAR = (("each side (torsion)", "ต่อข้าง (รับแรงบิด)"), ("(closed)", "(ปลอกปิด)"), (" legs", " ขา"),
          (" per b-face", " ต่อด้าน b"), (" per h-face", " ต่อด้าน h"))


def rebar_th(text: str) -> str:
    """Thai words in a bar description such as 'RB9 @ 0.150 m, 2 legs (closed)'."""
    for en, th in _REBAR:
        text = text.replace(en, th)
    return text


TH_MONTHS = ("มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", "กันยายน",
             "ตุลาคม", "พฤศจิกายน", "ธันวาคม")


def thai_date(d) -> str:
    """24 พฤศจิกายน 2569, 22:21 (Buddhist era year)."""
    return f"{d.day} {TH_MONTHS[d.month - 1]} {d.year + 543}, {d:%H:%M}"
