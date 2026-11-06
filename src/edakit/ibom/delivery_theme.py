"""Compact engineering-dialog theme using standard ttk widget elements."""
import tkinter as tk
from tkinter import ttk
from tkinter.font import nametofont

BG, PANEL, TEXT, MUTED = '#efefef', '#f5f5f5', '#202020', '#626262'
BORDER, BLUE, SELECTED = '#ababab', '#245885', '#d9e7f3'
FONT = ('Microsoft YaHei UI', 10)
OUTPUT_SELECTED = '#f6f9fc'


def install(root):
    style = ttk.Style(root)
    # Predictable rectangular fields and visible arrows, without image assets.
    style.theme_use('clam')
    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont'):
        nametofont(name, root=root).configure(family=FONT[0], size=FONT[1])
    style.configure('.', font=FONT, background=PANEL, foreground=TEXT)
    style.configure('TFrame', background=PANEL)
    style.configure('ED.Background.TFrame', background=BG)
    style.configure('ED.Panel.TFrame', background=PANEL, borderwidth=1, relief='solid')
    style.configure('TLabel', background=PANEL, foreground=TEXT)
    style.configure('ED.Title.TLabel', font=(FONT[0], 10, 'bold'), background=BG)
    style.configure('ED.Heading.TLabel', font=(FONT[0], 10, 'bold'))
    style.configure('ED.Material.TFrame', background='#fff', borderwidth=1, relief='solid', bordercolor='#c5c8cb')
    style.configure('ED.Material.TLabel', background='#fff')
    style.configure('ED.MaterialTitle.TLabel', background='#fff', font=(FONT[0], 10, 'bold'))
    style.configure('ED.ListHeader.TFrame', background='#e9e9e9')
    style.configure('ED.ListHeader.TLabel', background='#e9e9e9', foreground=MUTED, font=(FONT[0], 9))
    style.configure('ED.List.TFrame', background='#fff', borderwidth=1, relief='solid', bordercolor='#c1c5c8')
    style.configure('ED.Section.TLabel', font=(FONT[0], 10, 'bold'))
    style.configure('ED.PageTitle.TLabel', font=(FONT[0], 11, 'bold'))
    style.configure('ED.White.TFrame', background='#fff')
    style.configure('ED.WhiteMuted.TLabel', background='#fff', foreground=MUTED, font=(FONT[0], 9))
    style.configure('ED.Source.TRadiobutton', background='#fff', font=(FONT[0], 10, 'bold'), padding=(0, 1))
    style.map('ED.Source.TRadiobutton', background=[('active', '#fff')])
    style.configure('ED.Field.TLabel', font=FONT)
    style.configure('ED.Muted.TLabel', font=(FONT[0], 9), foreground=MUTED)
    style.configure('ED.Caption.TLabel', font=(FONT[0], 9), foreground=MUTED, background=BG)
    for name in ('ED.Badge.TLabel', 'ED.Note.TLabel'):
        style.configure(name, font=(FONT[0], 9), background=PANEL, foreground=MUTED, padding=(0, 3))
    style.configure('TLabelframe', background=PANEL, bordercolor=BORDER, borderwidth=1, relief='solid')
    style.configure('TLabelframe.Label', background=PANEL, foreground=TEXT, font=FONT)
    style.configure('TButton', font=FONT, padding=(10, 4), background='#e5e5e5', borderwidth=1, relief='raised')
    style.map('TButton', background=[('active', '#e2edf7')], bordercolor=[('focus', BLUE)])
    style.configure('ED.Primary.TButton', foreground='#fff', padding=(14, 4), bordercolor=BLUE, background='#2d6088')
    style.map('ED.Primary.TButton', background=[('disabled', '#ddd'), ('active', '#234f72')], foreground=[('disabled', MUTED), ('!disabled', '#fff')])
    style.configure('ED.Link.TButton', font=(FONT[0], 9), padding=(6, 2))
    for name in ('ED.Choice.TRadiobutton', 'ED.Nav.TRadiobutton'):
        style.configure(name, font=FONT, padding=(5, 3), background=PANEL)
        style.map(name, background=[('active', PANEL), ('selected', PANEL)], foreground=[('disabled', MUTED), ('!disabled', TEXT)])
    style.configure('TCheckbutton', font=FONT, padding=(2, 4), background=PANEL)
    style.map('TCheckbutton', background=[('active', PANEL)])
    style.configure('ED.Output.TCheckbutton', font=(FONT[0], 10, 'bold'), padding=(8, 8), background=PANEL)
    style.map('ED.Output.TCheckbutton', background=[('selected', SELECTED), ('active', PANEL)], foreground=[('disabled', MUTED), ('!disabled', TEXT)])
    style.configure('TEntry', font=FONT, padding=(6, 5), fieldbackground='#fff', bordercolor='#8e8e8e')
    style.configure('TCombobox', font=FONT, padding=(6, 5), arrowsize=14, fieldbackground='#fff', bordercolor='#8e8e8e')
    style.map('TCombobox', fieldbackground=[('readonly', '#fff')], foreground=[('disabled', MUTED), ('readonly', TEXT)], selectbackground=[('readonly', '#fff')], selectforeground=[('readonly', TEXT)])
    style.configure('TNotebook', background=BG, borderwidth=1, tabmargins=(4, 0, 0, 0))
    style.configure('TNotebook.Tab', background='#d6d6d6', padding=(15, 7), font=FONT)
    style.map('TNotebook.Tab', background=[('selected', PANEL)], foreground=[('selected', TEXT)])
    style.configure('Treeview', background='#fff', fieldbackground='#fff', foreground=TEXT, rowheight=round(nametofont('TkDefaultFont', root=root).metrics('linespace')*1.55), borderwidth=1)
    style.map('Treeview', background=[('selected', SELECTED)], foreground=[('selected', TEXT)])
    style.configure('Treeview.Heading', background='#dedede', font=FONT, padding=(5, 4))
    style.configure('ED.Navigation.TFrame', background='#eeeeee', borderwidth=1, relief='solid')
    style.configure('ED.Navigation.TLabel', background='#eeeeee', font=FONT)
    style.layout('ED.Workspace.TNotebook.Tab', [])
    style.configure('ED.Workspace.TNotebook', background=PANEL, borderwidth=1)
    style.layout('ED.Nav.TRadiobutton', [('Radiobutton.padding', {'sticky': 'nsew', 'children': [('Radiobutton.label', {'sticky': 'w'})]})])
    style.configure('ED.Nav.TRadiobutton', background='#eeeeee', padding=(9, 7), anchor='w')
    style.map('ED.Nav.TRadiobutton', background=[('selected', SELECTED), ('active', '#e5edf5')], foreground=[('selected', TEXT)])
    style.configure('ED.Toolbar.TButton', font=(FONT[0], 9), padding=(7, 3), borderwidth=1)
    style.configure('ED.Film.Treeview', font=(FONT[0], 9), rowheight=25, background='#fff', fieldbackground='#fff')
    style.configure('ED.PropertyName.TLabel', background='#eeeeee', padding=(7, 4), font=(FONT[0], 9))
    style.configure('ED.PropertyValue.TLabel', background='#fff', padding=(7, 4), font=(FONT[0], 9))
    # Keep ttk interaction and keyboard behavior, with quieter tile surfaces.
    style.layout('ED.Choice.TRadiobutton', [('Button.border', {'sticky': 'nsew', 'children': [
        ('Radiobutton.padding', {'sticky': 'nsew', 'children': [
            ('Radiobutton.label', {'sticky': 'nsew'})]})]})])
    style.configure('ED.Choice.TRadiobutton', background='#fff', bordercolor='#c6cbd0',
                    lightcolor='#fff', darkcolor='#fff', borderwidth=1, relief='solid', padding=(11, 6))
    style.map('ED.Choice.TRadiobutton', background=[('disabled', '#eeeeee'), ('selected', '#dfeaf5'), ('active', '#edf3f8'), ('!selected', '#fff')],
              bordercolor=[('disabled', '#d4d4d4'), ('selected', BLUE), ('focus', BLUE), ('active', '#829bb0')],
              foreground=[('disabled', MUTED), ('selected', '#174d77'), ('!selected', TEXT)],
              lightcolor=[('selected', '#dfeaf5'), ('active', '#edf3f8')], darkcolor=[('selected', '#dfeaf5'), ('active', '#edf3f8')])
    root.delivery_check_images = []
    scale = max(1, float(root.tk.call('tk', 'scaling'))/(96/72))
    def choice_surface(fill, border, thickness=1):
        size = round(12*scale)
        image = tk.PhotoImage(master=root, width=size, height=size)
        def inside(x, y, inset):
            lo, hi, radius = inset, 12-inset, max(0, 3-inset)
            if not (lo <= x < hi and lo <= y < hi):
                return False
            cx, cy = min(max(x, lo+radius), hi-radius), min(max(y, lo+radius), hi-radius)
            return (x-cx)**2+(y-cy)**2 <= radius**2
        for y in range(size):
            for x in range(size):
                px, py = (x+.5)/scale, (y+.5)/scale
                if inside(px, py, 0):
                    image.put(fill if inside(px, py, thickness) else border, (x, y))
        root.delivery_check_images.append(image)
        return image
    style.element_create('ED.Choice.border', 'image', choice_surface('#fff', '#b4b7ba'),
                         ('disabled', choice_surface('#eee', '#d4d4d4')),
                         ('selected', choice_surface('#e1ecf6', '#346c99', 2)),
                         ('focus', choice_surface('#fff', BLUE)),
                         ('active', choice_surface('#edf3f8', BLUE)),
                         border=round(4*scale), sticky='nsew')
    style.layout('ED.Choice.TRadiobutton', [('ED.Choice.border', {'sticky': 'nsew', 'children': [
        ('Radiobutton.padding', {'sticky': 'nsew', 'children': [
            ('Radiobutton.label', {'sticky': 'nsew'})]})]})])
    def check_image(selected, disabled=False):
        size = round(18*scale)
        image = tk.PhotoImage(master=root, width=size, height=size)
        for y in range(size):
            for x in range(size):
                px, py = x/scale, y/scale
                if 1 <= px < 17 and 1 <= py < 17:
                    color = '#a8b4bf' if disabled else BLUE if selected else '#a5afb8'
                    if 2 <= px < 16 and 2 <= py < 16:
                        color = '#a8b4bf' if disabled and selected else BLUE if selected else '#fff'
                    if selected and ((4 <= px <= 8 and abs(py-(px+2)) < 1.2) or (7 <= px <= 14 and abs(py-(17-px)) < 1.2)):
                        color = '#fff'
                    image.put(color, (x, y))
        root.delivery_check_images.append(image)
        return image
    style.element_create('ED.Output.indicator', 'image', check_image(False),
                         ('disabled selected', check_image(True, True)), ('selected', check_image(True)),
                         ('disabled', check_image(False, True)), sticky='w')
    style.layout('ED.Output.TCheckbutton', [
        ('Checkbutton.padding', {'sticky': 'nsew', 'children': [
            ('ED.Output.indicator', {'side': 'left', 'sticky': 'w'}),
            ('Checkbutton.label', {'side': 'left', 'sticky': 'w'})]})])
    style.configure('ED.Output.TCheckbutton', background='#fff', bordercolor='#c8cdd2',
                    lightcolor='#fff', darkcolor='#fff', borderwidth=0, relief='flat')
    style.map('ED.Output.TCheckbutton', background=[('selected', OUTPUT_SELECTED), ('active', '#f6f8fa'), ('!selected', '#fff')],
              bordercolor=[('selected', '#86a5bf'), ('focus', BLUE), ('active', '#86a5bf')],
              lightcolor=[('selected', OUTPUT_SELECTED)], darkcolor=[('selected', OUTPUT_SELECTED)])
    style.layout('ED.Setting.TCheckbutton', [('Checkbutton.padding', {'sticky': 'nsew', 'children': [
        ('ED.Output.indicator', {'side': 'left', 'sticky': 'w'}),
        ('Checkbutton.focus', {'side': 'left', 'sticky': 'w', 'children': [('Checkbutton.label', {'sticky': 'w'})]})]})])
    style.configure('ED.Setting.TCheckbutton', background=PANEL, font=FONT, padding=(0, 4))
    style.map('ED.Setting.TCheckbutton', background=[('active', PANEL)])
    root.configure(background=BG)
    return style
